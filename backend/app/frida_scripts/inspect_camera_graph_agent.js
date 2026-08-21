'use strict';

import ObjC from 'frida-objc-bridge';

function inspect(className) {
  const klass = ObjC.classes[className];
  if (!klass) return [];
  return ObjC.chooseSync(klass).map(function (object) {
    const ivars = {};
    Object.keys(object.$ivars).forEach(function (name) {
      try {
        const value = object.$ivars[name];
        if (value && value.$className) {
          ivars[name] = value.$className;
        } else {
          const text = String(value);
          ivars[name] = text.length > 100 ? text.slice(0, 100) : text;
        }
      } catch (error) {
        ivars[name] = `<unavailable: ${String(error)}>`;
      }
    });
    return { className: object.$className, ivars: ivars };
  });
}

send({
  type: 'camera-graph',
  scanner: inspect('WAWebClientQRCodeScannerViewController'),
  captureManager: inspect('FBCaptureManager'),
  cameraController: inspect('WACameraController'),
});
