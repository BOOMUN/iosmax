'use strict';

import ObjC from 'frida-objc-bridge';

function safe(label, callback) {
  try {
    const value = callback();
    if (value === null || value === undefined) return { label, value: 'null' };
    if (value.$className) return {
      label,
      handle: value.handle.toString(),
      className: value.$className,
      value: value.toString(),
    };
    return { label, value: String(value) };
  } catch (error) {
    return { label, error: String(error) };
  }
}

const rows = ObjC.chooseSync(ObjC.classes.BWMRCNode).map((node) => {
  const output = node.$ivars._output;
  const probes = [
    safe('node.output()', () => node.output()),
    safe('output.consumer()', () => output.consumer()),
    safe('output.connection()', () => output.connection()),
  ];
  let connection = null;
  try { connection = output.connection(); } catch (_) {}
  if (connection) {
    probes.push(safe('connection.input()', () => connection.input()));
    probes.push(safe('connection.output()', () => connection.output()));
    try {
      const input = connection.input();
      probes.push(safe('connection.input().node()', () => input.node()));
      probes.push(safe('connection.input().node().receiverPID KVC', () => input.node().valueForKey_('_receiverPID')));
    } catch (_) {}
  }
  return { node: node.toString(), output: output.toString(), probes };
});

send({ type: 'mrc-route', rows });
