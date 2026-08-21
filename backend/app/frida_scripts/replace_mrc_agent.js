'use strict';

import ObjC from 'frida-objc-bridge';

const getImageBuffer = new NativeFunction(
  Module.getGlobalExportByName('CMSampleBufferGetImageBuffer'),
  'pointer',
  ['pointer']
);
const getWidth = new NativeFunction(Module.getGlobalExportByName('CVPixelBufferGetWidth'), 'ulong', ['pointer']);
const getHeight = new NativeFunction(Module.getGlobalExportByName('CVPixelBufferGetHeight'), 'ulong', ['pointer']);
const getPixelFormat = new NativeFunction(Module.getGlobalExportByName('CVPixelBufferGetPixelFormatType'), 'uint', ['pointer']);
const createColorSpace = new NativeFunction(Module.getGlobalExportByName('CGColorSpaceCreateDeviceRGB'), 'pointer', []);

const ciImageClass = ObjC.classes.CIImage;
const ciColorClass = ObjC.classes.CIColor;
const ciContext = ObjC.classes.CIContext.contextWithOptions_(NULL);
ciContext.retain();
const colorSpace = createColorSpace();
const prepared = new Map();
let sourceImage = null;
let enabled = false;
let replaced = 0;

function rect(x, y, width, height) {
  return [[x, y], [width, height]];
}

function transform(scale, tx, ty) {
  return [scale, 0, 0, scale, tx, ty];
}

function preparedImage(width, height) {
  const key = `${width}x${height}`;
  if (prepared.has(key)) return prepared.get(key);
  const extent = sourceImage.extent();
  const origin = extent[0];
  const size = extent[1];
  const target = Math.min(width, height) * 0.82;
  const scale = target / Math.max(size[0], size[1]);
  const scaledWidth = size[0] * scale;
  const scaledHeight = size[1] * scale;
  const tx = (width - scaledWidth) / 2 - origin[0] * scale;
  const ty = (height - scaledHeight) / 2 - origin[1] * scale;
  const foreground = sourceImage.imageByApplyingTransform_(transform(scale, tx, ty));
  const background = ciImageClass
    .imageWithColor_(ciColorClass.colorWithRed_green_blue_alpha_(1, 1, 1, 1))
    .imageByCroppingToRect_(rect(0, 0, width, height));
  const image = foreground.imageByCompositingOverImage_(background);
  image.retain();
  prepared.set(key, image);
  return image;
}

const method = ObjC.classes.BWMRCNode['- renderSampleBuffer:forInput:'];
const listener = Interceptor.attach(method.implementation, {
  onEnter(args) {
    if (!enabled || sourceImage === null) return;
    try {
      const imageBuffer = getImageBuffer(args[2]);
      if (imageBuffer.isNull()) return;
      const width = Number(getWidth(imageBuffer));
      const height = Number(getHeight(imageBuffer));
      const pixelFormat = Number(getPixelFormat(imageBuffer));
      const image = preparedImage(width, height);
      ciContext.render_toCVPixelBuffer_bounds_colorSpace_(
        image,
        imageBuffer,
        rect(0, 0, width, height),
        colorSpace
      );
      replaced += 1;
      if (replaced === 1 || replaced % 10 === 0) {
        send({ type: 'mrc-frame-replaced', replaced, width, height, pixelFormat });
      }
    } catch (error) {
      enabled = false;
      send({ type: 'mrc-replace-error', message: String(error), stack: error.stack });
    }
  },
});

recv('set-frame', function receive(message, data) {
  try {
    const bytes = new Uint8Array(data);
    const storage = Memory.alloc(bytes.byteLength);
    storage.writeByteArray(bytes);
    const nsData = ObjC.classes.NSData.dataWithBytes_length_(storage, bytes.byteLength);
    sourceImage = ciImageClass.imageWithData_(nsData);
    if (sourceImage === null) throw new Error('CIImage could not decode PNG');
    sourceImage.retain();
    enabled = true;
    send({ type: 'mrc-replacer-ready', bytes: bytes.byteLength });
  } catch (error) {
    enabled = false;
    send({ type: 'mrc-replace-error', message: String(error), stack: error.stack });
  }
});

setTimeout(() => {
  enabled = false;
  listener.detach();
  send({ type: 'mrc-replacer-stopped', replaced });
}, 9000);
