'use strict';

import ObjC from 'frida-objc-bridge';

function globalExport(name) {
  return Module.getGlobalExportByName(name);
}

const getImageBuffer = new NativeFunction(globalExport('CMSampleBufferGetImageBuffer'), 'pointer', ['pointer']);
const getWidth = new NativeFunction(globalExport('CVPixelBufferGetWidth'), 'ulong', ['pointer']);
const getHeight = new NativeFunction(globalExport('CVPixelBufferGetHeight'), 'ulong', ['pointer']);
const getPixelFormat = new NativeFunction(globalExport('CVPixelBufferGetPixelFormatType'), 'uint', ['pointer']);
const method = ObjC.classes.BWMRCNode['- renderSampleBuffer:forInput:'];
const formats = {};
let count = 0;

const listener = Interceptor.attach(method.implementation, {
  onEnter(args) {
    count += 1;
    try {
      const imageBuffer = getImageBuffer(args[2]);
      if (imageBuffer.isNull()) return;
      const width = Number(getWidth(imageBuffer));
      const height = Number(getHeight(imageBuffer));
      const pixelFormat = Number(getPixelFormat(imageBuffer));
      const key = `${width}x${height}-${pixelFormat}`;
      formats[key] = (formats[key] || 0) + 1;
    } catch (_) {}
  },
});

setTimeout(() => {
  send({ type: 'mrc-buffer-probe', pid: Process.id, count, formats });
  listener.detach();
}, 6000);
