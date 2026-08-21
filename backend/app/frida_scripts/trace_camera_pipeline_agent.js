'use strict';

import ObjC from 'frida-objc-bridge';

const targetClasses = [
  'WAWebClientQRCodeScannerViewController',
  'WAOneCameraController',
  'FBCaptureManager',
  'FBCaptureSession',
  'FBCaptureVideoDataOutput',
  'FBAVVideoDataProducer',
];

function interesting(method) {
  return /(capture|sample|buffer|video|frame|output|producer|consumer|session|metadata|pixel|image|qr|scan|detect|code)/i.test(method);
}

function summarizeValue(value) {
  if (value === null || value === undefined) return 'null';
  try {
    if (value.$className) return value.$className;
    const text = String(value);
    return text.length > 160 ? `${text.slice(0, 160)}…` : text;
  } catch (error) {
    return `<unavailable: ${String(error)}>`;
  }
}

function inspectClass(className) {
  const klass = ObjC.classes[className];
  if (!klass) return { className, available: false, methods: [], instances: [] };
  const methods = klass.$ownMethods.filter(interesting).sort();
  const instances = ObjC.chooseSync(klass).map((object) => {
    const ivars = {};
    Object.keys(object.$ivars).forEach((name) => {
      if (interesting(name)) {
        try {
          ivars[name] = summarizeValue(object.$ivars[name]);
        } catch (error) {
          ivars[name] = `<unavailable: ${String(error)}>`;
        }
      }
    });
    return { className: object.$className, ivars };
  });
  return { className, available: true, methods, instances };
}

send({
  type: 'pipeline-inventory',
  classes: targetClasses.map(inspectClass),
});
