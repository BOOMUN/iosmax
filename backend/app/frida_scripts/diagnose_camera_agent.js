'use strict';

import ObjC from 'frida-objc-bridge';

function nsString(value) {
  return ObjC.classes.NSString.stringWithUTF8String_(Memory.allocUtf8String(value));
}

recv('decode', function (_message, data) {
  try {
    send({ type: 'stage', name: 'received', bytes: data.byteLength });
    const bytes = new Uint8Array(data);
    const storage = Memory.alloc(bytes.byteLength);
    storage.writeByteArray(bytes);
    const nsData = ObjC.classes.NSData.dataWithBytes_length_(storage, bytes.byteLength);
    const uiImage = ObjC.classes.UIImage.imageWithData_(nsData);
    send({ type: 'stage', name: 'uiimage', ok: uiImage !== null });
    const image = ObjC.classes.CIImage.imageWithCGImage_(uiImage.CGImage());
    send({ type: 'stage', name: 'ciimage', extent: image.extent() });
    const options = ObjC.classes.NSDictionary.dictionaryWithObject_forKey_(
      nsString('CIDetectorAccuracyHigh'),
      nsString('CIDetectorAccuracy')
    );
    const detector = ObjC.classes.CIDetector.detectorOfType_context_options_(
      nsString('CIDetectorTypeQRCode'),
      NULL,
      options
    );
    send({ type: 'stage', name: 'detector', ok: detector !== null });
    const features = detector.featuresInImage_(image);
    send({ type: 'stage', name: 'features', count: Number(features.count()) });
    if (features.count() > 0) {
      const feature = features.objectAtIndex_(0);
      const message = feature.messageString();
      send({ type: 'stage', name: 'message', value: message.toString() });
      send({
        type: 'stage',
        name: 'feature-methods',
        methods: feature.$methods.filter(function (name) {
          return /(symbol|descriptor|payload|message|bounds)/i.test(name);
        }),
      });
    }
  } catch (error) {
    send({ type: 'diagnostic-error', message: String(error), stack: error.stack });
  }
});
