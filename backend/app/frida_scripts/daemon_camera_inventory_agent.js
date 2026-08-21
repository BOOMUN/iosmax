'use strict';

import ObjC from 'frida-objc-bridge';

const moduleFilter = /(CMCapture|AVFCapture|H13ISP|appleh13camerad|mediaserverd)/i;
const classFilter = /(capture|camera|stream|remote|client|source|sink|output|connection)/i;
const methodFilter = /(sample|buffer|surface|frame|output|stream|client|connection|enqueue|dequeue|send|deliver|consume|produce)/i;

const loaded = ObjC.enumerateLoadedClassesSync();
const inventory = [];

Object.keys(loaded).forEach((modulePath) => {
  if (!moduleFilter.test(modulePath)) return;
  loaded[modulePath].forEach((className) => {
    if (!classFilter.test(className)) return;
    const klass = ObjC.classes[className];
    if (!klass) return;
    const methods = klass.$ownMethods.filter((method) => methodFilter.test(method));
    if (methods.length === 0) return;
    inventory.push({ modulePath, className, methods: methods.slice(0, 80) });
  });
});

send({
  type: 'daemon-camera-inventory',
  process: Process.id,
  inventory: inventory.slice(0, 240),
  truncated: inventory.length > 240,
  total: inventory.length,
});
