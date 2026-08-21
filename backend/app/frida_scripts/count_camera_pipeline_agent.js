'use strict';

import ObjC from 'frida-objc-bridge';

const candidates = [
  ['FBCaptureManager', '- captureOutput:didOutputSampleBuffer:fromConnection:'],
  ['FBCaptureManager', '- _handleVideoSampleBuffer:depthData:fromConnection:'],
  ['FBCaptureManager', '- handleVideoSampleBuffer:depthData:fromConnection:'],
  ['FBAVVideoDataProducer', '- produceVideoDataWithSampleBuffer:depthData:fromConnection:videoDeviceInput:videoBufferTransform:skipFilterRendering:isMultiCameraStreamEnabled:'],
  ['FBAVVideoDataProducer', '- _produceVideoDataWithSampleBuffer:depthData:videoDeviceInput:videoBufferTransform:skipFilterRendering:isMultiCameraStreamEnabled:metadata:'],
  ['WAOneCameraController', '- handleVideoBuffer:'],
  ['FBCaptureManager', '- _didDetectObject:'],
  ['WAOneCameraController', '- cameraManager:didDetectQrCode:data:time:bounds:symbolVersion:'],
  ['WAWebClientQRCodeScannerViewController', '- cameraController:didDetectQRCode:'],
  ['WAWebClientQRCodeScannerViewController', '- willAcceptQRCode'],
  ['WAWebClientQRCodeScannerViewController', '- didAcceptQRCode'],
];

const counts = {};
const listeners = [];

candidates.forEach(([className, selector]) => {
  const klass = ObjC.classes[className];
  const method = klass ? klass[selector] : null;
  const key = `${className} ${selector}`;
  counts[key] = 0;
  if (!method) return;
  listeners.push(Interceptor.attach(method.implementation, {
    onEnter() {
      counts[key] += 1;
    },
  }));
});

const callers = {};
let getterCalls = 0;
const getter = Module.getGlobalExportByName('CMSampleBufferGetImageBuffer');
listeners.push(Interceptor.attach(getter, {
  onEnter() {
    getterCalls += 1;
    if (getterCalls > 600) return;
    const symbol = DebugSymbol.fromAddress(this.returnAddress);
    const key = `${symbol.moduleName || '?'}!${symbol.name || this.returnAddress}`;
    callers[key] = (callers[key] || 0) + 1;
  },
}));

setTimeout(() => {
  send({ type: 'pipeline-counts', counts, getterCalls, callers });
  listeners.forEach((listener) => listener.detach());
}, 8000);
