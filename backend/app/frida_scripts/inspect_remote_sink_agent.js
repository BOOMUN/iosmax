'use strict';

import ObjC from 'frida-objc-bridge';

const klass = ObjC.classes.BWRemoteQueueSinkNode;
const selector = '- renderSampleBuffer:forInput:';
const counts = {};

function summarize(value) {
  if (value === null || value === undefined) return 'null';
  try {
    if (value.$className) {
      let description = '';
      try { description = value.toString(); } catch (_) {}
      if (description.length > 180) description = `${description.slice(0, 180)}…`;
      return { className: value.$className, description };
    }
    const text = String(value);
    return text.length > 180 ? `${text.slice(0, 180)}…` : text;
  } catch (error) {
    return `<unavailable: ${String(error)}>`;
  }
}

function inspect(object) {
  const ivars = {};
  Object.keys(object.$ivars).forEach((name) => {
    if (!/(client|connection|source|input|output|queue|session|pid|application|bundle|remote|sink|port|name)/i.test(name)) return;
    try { ivars[name] = summarize(object.$ivars[name]); }
    catch (error) { ivars[name] = `<unavailable: ${String(error)}>`; }
  });
  return { handle: object.handle.toString(), className: object.$className, ivars };
}

const listener = Interceptor.attach(klass[selector].implementation, {
  onEnter(args) {
    const key = args[0].toString();
    counts[key] = (counts[key] || 0) + 1;
  },
});

setTimeout(() => {
  const instances = ObjC.chooseSync(klass).map(inspect);
  send({ type: 'remote-sink-inventory', pid: Process.id, counts, instances });
  listener.detach();
}, 6000);
