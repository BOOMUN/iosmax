'use strict';

import ObjC from 'frida-objc-bridge';

const classNames = ['BWMRCNode', 'BWPixelTransferNode'];
const counts = {};
const listeners = [];

function summarize(value) {
  if (value === null || value === undefined) return 'null';
  try {
    if (value.$className) {
      let description = '';
      try { description = value.toString(); } catch (_) {}
      if (description.length > 220) description = `${description.slice(0, 220)}…`;
      return { handle: value.handle.toString(), className: value.$className, description };
    }
    const text = String(value);
    return text.length > 220 ? `${text.slice(0, 220)}…` : text;
  } catch (error) {
    return `<unavailable: ${String(error)}>`;
  }
}

function inspect(object) {
  const ivars = {};
  Object.keys(object.$ivars).forEach((name) => {
    try { ivars[name] = summarize(object.$ivars[name]); }
    catch (error) { ivars[name] = `<unavailable: ${String(error)}>`; }
  });
  return { handle: object.handle.toString(), description: summarize(object), ivars };
}

const classes = {};
classNames.forEach((className) => {
  const klass = ObjC.classes[className];
  if (!klass) return;
  classes[className] = { methods: klass.$ownMethods, instances: ObjC.chooseSync(klass).map(inspect) };
  klass.$ownMethods.filter((method) => /(render|sample|buffer|detect|process|code|metadata)/i.test(method)).forEach((selector) => {
    const key = `${className} ${selector}`;
    counts[key] = 0;
    const method = klass[selector];
    if (!method) return;
    listeners.push(Interceptor.attach(method.implementation, {
      onEnter() { counts[key] += 1; },
    }));
  });
});

setTimeout(() => {
  send({ type: 'mrc-inventory', pid: Process.id, classes, counts });
  listeners.forEach((listener) => listener.detach());
}, 6000);
