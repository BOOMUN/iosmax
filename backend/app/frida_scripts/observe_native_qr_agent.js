'use strict';

import ObjC from 'frida-objc-bridge';

function isNil(value) {
  return value === null || value === undefined || (value.handle && value.handle.isNull());
}

function inspectQrObject(object, metadata) {
  const result = { objectClass: object.$className };
  const code = typeof object.code === 'function' ? object.code() : null;
  const data = typeof object.data === 'function' ? object.data() : null;
  const metadataString = metadata && typeof metadata.stringValue === 'function'
    ? metadata.stringValue()
    : null;

  result.codeClass = isNil(code) ? null : code.$className;
  result.codeLength = isNil(code) ? 0 : code.toString().length;
  result.dataClass = isNil(data) ? null : data.$className;
  result.dataLength = isNil(data) || typeof data.length !== 'function' ? 0 : Number(data.length());
  result.symbolVersion = typeof object.symbolVersion === 'function'
    ? Number(object.symbolVersion())
    : null;
  result.metadataClass = metadata ? metadata.$className : null;
  result.metadataTextLength = isNil(metadataString) ? 0 : metadataString.toString().length;

  if (!isNil(code) && !isNil(metadataString) && typeof code.isEqualToString_ === 'function') {
    result.codeEqualsMetadataText = Boolean(code.isEqualToString_(metadataString));
  }
  if (!isNil(data) && !isNil(metadataString) && typeof data.isEqualToData_ === 'function') {
    const utf8Data = metadataString.dataUsingEncoding_(4);
    result.dataEqualsMetadataUtf8 = Boolean(data.isEqualToData_(utf8Data));
  }
  return result;
}

if (!ObjC.available) {
  send({ type: 'observer-error', message: 'Objective-C runtime unavailable' });
} else {
  const factory = ObjC.classes.WACameraController['- qrCodeObjectWithMetadataObject:'];
  const delivery = ObjC.classes.WAWebClientQRCodeScannerViewController[
    '- cameraController:didDetectQRCode:'
  ];
  const metadataDelivery = ObjC.classes.WACameraController[
    '- captureOutput:didOutputMetadataObjects:fromConnection:'
  ];

  Interceptor.attach(metadataDelivery.implementation, {
    onEnter(args) {
      try {
        const objects = new ObjC.Object(args[3]);
        const count = Number(objects.count());
        if (count === 0) return;
        const first = objects.objectAtIndex_(0);
        const stringValue = typeof first.stringValue === 'function' ? first.stringValue() : null;
        send({
          type: 'camera-metadata-observed',
          count: count,
          objectClass: first.$className,
          textLength: isNil(stringValue) ? 0 : stringValue.toString().length,
        });
      } catch (error) {
        send({ type: 'observer-error', stage: 'metadata', message: String(error) });
      }
    },
  });

  Interceptor.attach(factory.implementation, {
    onEnter(args) {
      this.metadataPointer = args[2];
    },
    onLeave(retval) {
      try {
        if (retval.isNull()) return;
        const object = new ObjC.Object(retval);
        const metadata = this.metadataPointer.isNull()
          ? null
          : new ObjC.Object(this.metadataPointer);
        send({ type: 'native-qr-created', details: inspectQrObject(object, metadata) });
      } catch (error) {
        send({ type: 'observer-error', stage: 'factory', message: String(error) });
      }
    },
  });

  Interceptor.attach(delivery.implementation, {
    onEnter(args) {
      try {
        const object = new ObjC.Object(args[3]);
        send({ type: 'native-qr-delivered', details: inspectQrObject(object, null) });
      } catch (error) {
        send({ type: 'observer-error', stage: 'delivery', message: String(error) });
      }
    },
  });
  send({ type: 'observer-ready' });
}
