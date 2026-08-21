'use strict';

import ObjC from 'frida-objc-bridge';

if (!ObjC.available) {
  send({ type: 'agent-error', message: '当前进程不支持 Objective-C Runtime' });
} else {
  const hookedClasses = new Set();
  const hookedImplementations = new Set();
  const selector = '- captureOutput:didOutputSampleBuffer:fromConnection:';
  const preparedImages = new Map();
  let enabled = false;
  let qrImage = null;
  let qrCodeObject = null;
  let activeCameraController = null;
  let activeMetadataOutput = null;
  let activeMetadataConnection = null;
  let deliveryTimer = null;
  let delivered = false;
  let injectingMetadata = false;
  let metadataPlaceholder = null;
  let frameCount = 0;
  let pipelineReported = false;
  let renderErrorReported = false;
  let videoControllerReported = false;

  function getGlobalExport(name) {
    if (typeof Module.getGlobalExportByName === 'function') {
      return Module.getGlobalExportByName(name);
    }
    return Module.getExportByName(null, name);
  }

  const CMSampleBufferGetImageBuffer = new NativeFunction(
    getGlobalExport('CMSampleBufferGetImageBuffer'),
    'pointer',
    ['pointer']
  );
  const CVPixelBufferGetWidth = new NativeFunction(
    getGlobalExport('CVPixelBufferGetWidth'),
    'ulong',
    ['pointer']
  );
  const CVPixelBufferGetHeight = new NativeFunction(
    getGlobalExport('CVPixelBufferGetHeight'),
    'ulong',
    ['pointer']
  );
  const CGColorSpaceCreateDeviceRGB = new NativeFunction(
    getGlobalExport('CGColorSpaceCreateDeviceRGB'),
    'pointer',
    []
  );
  const CACurrentMediaTime = new NativeFunction(
    getGlobalExport('CACurrentMediaTime'),
    'double',
    []
  );

  const ciContext = ObjC.classes.CIContext.contextWithOptions_(NULL);
  ciContext.retain();
  const colorSpace = CGColorSpaceCreateDeviceRGB();
  const qrFactoryMethod = ObjC.classes.WACameraController[
    '- qrCodeObjectWithMetadataObject:'
  ];
  const originalQrFactory = new NativeFunction(
    qrFactoryMethod.implementation,
    'pointer',
    ['pointer', 'pointer', 'pointer']
  );
  const qrFactoryReplacement = new NativeCallback(function (self, command, metadata) {
    if (injectingMetadata && qrCodeObject !== null) return qrCodeObject.handle;
    return originalQrFactory(self, command, metadata);
  }, 'pointer', ['pointer', 'pointer', 'pointer']);
  Interceptor.replace(qrFactoryMethod.implementation, qrFactoryReplacement);

  function nsString(value) {
    return ObjC.classes.NSString.stringWithUTF8String_(Memory.allocUtf8String(value));
  }

  function rect(x, y, width, height) {
    return [[x, y], [width, height]];
  }

  function transform(scale, tx, ty) {
    return [scale, 0, 0, scale, tx, ty];
  }

  function clearPreparedImages() {
    preparedImages.forEach(function (image) { image.release(); });
    preparedImages.clear();
  }

  function releaseQrCodeObject() {
    if (qrCodeObject !== null) {
      qrCodeObject.release();
      qrCodeObject = null;
    }
  }

  function rememberCameraController(object) {
    if (
      !object ||
      !object.$className ||
      object.$className.indexOf('WACameraController') === -1 ||
      (activeCameraController !== null && activeCameraController.handle.equals(object.handle))
    ) return;
    if (activeCameraController !== null) activeCameraController.release();
    object.retain();
    activeCameraController = object;
    send({ type: 'camera-controller-captured', className: object.$className });
  }

  function releaseCameraController() {
    if (activeCameraController !== null) {
      activeCameraController.release();
      activeCameraController = null;
    }
  }

  function rememberMetadataPipeline(output, connection) {
    if (activeMetadataOutput !== null) activeMetadataOutput.release();
    if (activeMetadataConnection !== null) activeMetadataConnection.release();
    activeMetadataOutput = output && !output.isNull() ? new ObjC.Object(output).retain() : null;
    activeMetadataConnection = connection && !connection.isNull()
      ? new ObjC.Object(connection).retain()
      : null;
  }

  function releaseMetadataPipeline() {
    if (activeMetadataOutput !== null) {
      activeMetadataOutput.release();
      activeMetadataOutput = null;
    }
    if (activeMetadataConnection !== null) {
      activeMetadataConnection.release();
      activeMetadataConnection = null;
    }
  }

  function releaseMetadataPlaceholder() {
    if (metadataPlaceholder !== null) {
      metadataPlaceholder.release();
      metadataPlaceholder = null;
    }
  }

  function findMetadataOutput(controller) {
    try {
      const ivars = controller.$ivars;
      const names = Object.keys(ivars);
      for (let index = 0; index < names.length; index += 1) {
        const value = ivars[names[index]];
        if (
          value &&
          value.$className &&
          value.isKindOfClass_(ObjC.classes.AVCaptureMetadataOutput)
        ) return value;
      }
      for (let index = 0; index < names.length; index += 1) {
        const value = ivars[names[index]];
        if (
          !value ||
          !value.$className ||
          !value.isKindOfClass_(ObjC.classes.AVCaptureSession)
        ) continue;
        const outputs = value.outputs();
        for (let outputIndex = 0; outputIndex < outputs.count(); outputIndex += 1) {
          const output = outputs.objectAtIndex_(outputIndex);
          if (output.isKindOfClass_(ObjC.classes.AVCaptureMetadataOutput)) return output;
        }
      }
    } catch (error) {
      send({ type: 'metadata-output-warning', message: String(error) });
    }
    return null;
  }

  function buildQrCode(payload) {
    if (!payload || !payload.qrText || !payload.qrDataBase64) {
      throw new Error('缺少浏览器解码的二维码数据');
    }
    const symbolVersion = Number(payload.qrVersion);
    if (!Number.isInteger(symbolVersion) || symbolVersion < 1 || symbolVersion > 40) {
      throw new Error('二维码版本无效');
    }
    const data = ObjC.classes.NSData.alloc().initWithBase64EncodedString_options_(
      nsString(payload.qrDataBase64),
      0
    );
    if (!data || data.length() === 0) throw new Error('二维码原始数据解码失败');
    const parsedCode = ObjC.classes.WAQRCodeDataParser.parseFromData_symbolVersion_(data, symbolVersion);
    const dataLength = Number(data.length());
    const message = nsString(payload.qrText);
    const code = parsedCode || message;
    const object = ObjC.classes.WACameraQRCodeObject.alloc().init();
    object.setTime_(CACurrentMediaTime());
    object.setBounds_(rect(0.1, 0.1, 0.8, 0.8));
    object.setCode_(code);
    object.setSymbolVersion_(symbolVersion);
    object.setData_(data);
    object.retain();
    data.release();
    return {
      object: object,
      messageLength: payload.qrText.length,
      symbolVersion: symbolVersion,
      parsed: parsedCode !== null,
      dataLength: dataLength,
      codeClass: code.$className,
    };
  }

  function stopDeliveryTimer() {
    if (deliveryTimer !== null) {
      clearInterval(deliveryTimer);
      deliveryTimer = null;
    }
  }

  function deliverQrCode() {
    if (!enabled || delivered || qrCodeObject === null) return;
    if (activeCameraController === null) return;
    delivered = true;
    stopDeliveryTimer();
    activeCameraController.retain();
    const controller = activeCameraController;
    ObjC.schedule(ObjC.mainQueue, function () {
      try {
        const output = activeMetadataOutput || findMetadataOutput(controller);
        let connection = activeMetadataConnection || NULL;
        if (activeMetadataConnection === null && output !== null) {
          const connections = output.connections();
          if (connections.count() > 0) connection = connections.objectAtIndex_(0);
        }
        injectingMetadata = true;
        controller.captureOutput_didOutputMetadataObjects_fromConnection_(
          output || NULL,
          ObjC.classes.NSArray.arrayWithObject_(metadataPlaceholder),
          connection
        );
        send({
          type: 'metadata-dispatched',
          controllerClass: controller.$className,
          outputFound: output !== null,
        });
      } catch (error) {
        delivered = false;
        send({ type: 'agent-error', message: `Metadata 输入失败：${String(error)}` });
      } finally {
        injectingMetadata = false;
        controller.release();
      }
    });
  }

  function startDeliveryTimer() {
    stopDeliveryTimer();
    deliverQrCode();
    if (!delivered) deliveryTimer = setInterval(deliverQrCode, 250);
  }

  function prepareImage(width, height) {
    const key = width + 'x' + height;
    if (preparedImages.has(key)) return preparedImages.get(key);
    if (qrImage === null) return null;

    const extent = qrImage.extent();
    const origin = extent[0];
    const size = extent[1];
    const target = Math.min(width, height) * 0.82;
    const scale = target / Math.max(size[0], size[1]);
    const scaledWidth = size[0] * scale;
    const scaledHeight = size[1] * scale;
    const tx = (width - scaledWidth) / 2 - origin[0] * scale;
    const ty = (height - scaledHeight) / 2 - origin[1] * scale;
    const moved = qrImage.imageByApplyingTransform_(transform(scale, tx, ty));
    const white = ObjC.classes.CIImage
      .imageWithColor_(ObjC.classes.CIColor.colorWithRed_green_blue_alpha_(1, 1, 1, 1))
      .imageByCroppingToRect_(rect(0, 0, width, height));
    const result = moved.imageByCompositingOverImage_(white);
    result.retain();
    preparedImages.set(key, result);
    return result;
  }

  function replaceFrame(sampleBuffer) {
    const pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (pixelBuffer.isNull()) return;
    const width = Number(CVPixelBufferGetWidth(pixelBuffer));
    const height = Number(CVPixelBufferGetHeight(pixelBuffer));
    const image = prepareImage(width, height);
    if (image === null) return;
    ciContext.render_toCVPixelBuffer_bounds_colorSpace_(
      image,
      pixelBuffer,
      rect(0, 0, width, height),
      colorSpace
    );
    frameCount += 1;
    if (frameCount === 1 || frameCount % 30 === 0) {
      send({ type: 'frame-replaced', count: frameCount, width: width, height: height });
    }
  }

  function hookDelegateClass(className) {
    if (!className || hookedClasses.has(className)) return;
    const klass = ObjC.classes[className];
    if (!klass || !klass[selector]) return;
    const method = klass[selector];
    const implementationKey = method.implementation.toString();
    if (!hookedImplementations.has(implementationKey)) {
      try {
        Interceptor.attach(method.implementation, {
          onEnter(args) {
            try {
              const outputObject = new ObjC.Object(args[2]);
              const captureDelegate = new ObjC.Object(args[0]);
              if (outputObject.isKindOfClass_(ObjC.classes.AVCaptureVideoDataOutput)) {
                if (!videoControllerReported) {
                  videoControllerReported = true;
                  send({
                    type: 'video-controller-seen',
                    className: captureDelegate.$className,
                    outputClass: outputObject.$className,
                  });
                }
                rememberCameraController(captureDelegate);
              }
              if (
                enabled &&
                qrImage !== null &&
                outputObject.isKindOfClass_(ObjC.classes.AVCaptureVideoDataOutput)
              ) {
                if (!pipelineReported) {
                  pipelineReported = true;
                  send({ type: 'pipeline-detected', outputClass: outputObject.$className });
                }
                replaceFrame(args[3]);
              }
            } catch (error) {
              if (!renderErrorReported) {
                renderErrorReported = true;
                send({ type: 'agent-error', message: String(error) });
              }
            }
          },
        });
      } catch (error) {
        send({ type: 'hook-skipped', className: className, message: String(error) });
        hookedClasses.add(className);
        return;
      }
      hookedImplementations.add(implementationKey);
    }
    hookedClasses.add(className);
    send({ type: 'hook-installed', className: className });
  }

  function hookMetadataController() {
    const method = ObjC.classes.WACameraController[
      '- captureOutput:didOutputMetadataObjects:fromConnection:'
    ];
    if (!method) return;
    Interceptor.attach(method.implementation, {
      onEnter(args) {
        try {
          const controller = new ObjC.Object(args[0]);
          rememberCameraController(controller);
          rememberMetadataPipeline(args[2], args[4]);
          send({
            type: 'metadata-pipeline-captured',
            controllerClass: controller.$className,
            outputClass: args[2].isNull() ? null : new ObjC.Object(args[2]).$className,
          });
        } catch (error) {
          send({ type: 'metadata-output-warning', message: String(error) });
        }
      },
    });
  }

  function hookFutureDelegates() {
    const method = ObjC.classes.AVCaptureVideoDataOutput[
      '- setSampleBufferDelegate:queue:'
    ];
    Interceptor.attach(method.implementation, {
      onEnter(args) {
        const delegate = args[2];
        if (!delegate.isNull()) {
          hookDelegateClass(new ObjC.Object(delegate).$className);
        }
      },
    });
  }

  function hookScannerAcceptance() {
    const scanner = ObjC.classes.WAWebClientQRCodeScannerViewController;
    [
      ['- willAcceptQRCode', 'qr-will-accept'],
      ['- didAcceptQRCode', 'qr-accepted'],
    ].forEach(function (entry) {
      const method = scanner[entry[0]];
      if (!method) return;
      Interceptor.attach(method.implementation, {
        onEnter() {
          send({ type: entry[1] });
        },
      });
    });
  }

  function scanExistingDelegates() {
    const modules = ObjC.enumerateLoadedClassesSync();
    Object.keys(modules).forEach(function (moduleName) {
      modules[moduleName].forEach(function (className) {
        const klass = ObjC.classes[className];
        if (klass && klass.$ownMethods.indexOf(selector) !== -1) {
          hookDelegateClass(className);
        }
      });
    });
  }

  function receiveQr() {
    recv('set-qr', function (message, data) {
      try {
        const bytes = new Uint8Array(data);
        const storage = Memory.alloc(bytes.byteLength);
        storage.writeByteArray(bytes);
        const nsData = ObjC.classes.NSData.dataWithBytes_length_(storage, bytes.byteLength);
        const uiImage = ObjC.classes.UIImage.imageWithData_(nsData);
        if (uiImage === null) throw new Error('PNG 解码失败');
        clearPreparedImages();
        if (qrImage !== null) qrImage.release();
        qrImage = ObjC.classes.CIImage.imageWithCGImage_(uiImage.CGImage());
        qrImage.retain();
        releaseQrCodeObject();
        releaseMetadataPlaceholder();
        frameCount = 0;
        pipelineReported = false;
        renderErrorReported = false;
        const decoded = buildQrCode(message.payload);
        qrCodeObject = decoded.object;
        metadataPlaceholder = ObjC.classes.AVMetadataMachineReadableCodeObject.alloc().init();
        if (!metadataPlaceholder) throw new Error('无法创建 Metadata 占位对象');
        delivered = false;
        send({
          type: 'qr-ready',
          decoded: true,
          parsed: decoded.parsed,
          dataLength: decoded.dataLength,
          codeClass: decoded.codeClass,
          messageLength: decoded.messageLength,
          symbolVersion: decoded.symbolVersion,
        });
        if (enabled) startDeliveryTimer();
      } catch (error) {
        send({ type: 'agent-error', message: String(error) });
      }
      receiveQr();
    });
  }

  hookFutureDelegates();
  hookMetadataController();
  hookScannerAcceptance();
  scanExistingDelegates();
  receiveQr();

  recv('enable', function () {
    enabled = true;
    startDeliveryTimer();
  });
  recv('disable', function () {
    enabled = false;
    stopDeliveryTimer();
    releaseCameraController();
    releaseMetadataPipeline();
    releaseMetadataPlaceholder();
  });
}
