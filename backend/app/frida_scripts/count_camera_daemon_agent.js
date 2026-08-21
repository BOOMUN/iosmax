'use strict';

import ObjC from 'frida-objc-bridge';

const candidates = [
  ['CMCaptureFrameSenderService', '- _newSampleBufferToSendFromSampleBuffer:'],
  ['CMCaptureFrameSenderClient', '- sendXCPSampleBuffer:'],
  ['BWRemoteQueueSinkNode', '- renderSampleBuffer:forInput:'],
  ['BWFigVideoCaptureStream', '- sourceNodeWillEmitVideoSampleBuffer:drivesCameraControls:deliversStills:'],
  ['BWFigVideoCaptureDevice', '- captureStream:willEmitVideoSampleBuffer:drivesCameraControls:'],
  ['BWNodeOutput', '- emitSampleBuffer:'],
  ['FigCameraViewfinderStream', '- enqueueVideoSampleBuffer:'],
  ['AVCaptureMetadataOutput', '- _processSampleBuffer:'],
  ['AVCaptureVideoDataOutput', '- _processSampleBuffer:'],
];

const counts = {};
const availability = {};
const listeners = [];

candidates.forEach(([className, selector]) => {
  const key = `${className} ${selector}`;
  const klass = ObjC.classes[className];
  const method = klass ? klass[selector] : null;
  availability[key] = method !== null && method !== undefined;
  counts[key] = 0;
  if (!method) return;
  listeners.push(Interceptor.attach(method.implementation, {
    onEnter() {
      counts[key] += 1;
    },
  }));
});

setTimeout(() => {
  send({ type: 'daemon-pipeline-counts', pid: Process.id, availability, counts });
  listeners.forEach((listener) => listener.detach());
}, 8000);
