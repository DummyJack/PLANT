function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function writeUint16(bytes: number[], value: number) {
  bytes.push(value & 0xff, (value >>> 8) & 0xff);
}

function writeUint32(bytes: number[], value: number) {
  bytes.push(value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff);
}

function appendBytes(target: number[], bytes: Uint8Array) {
  for (const byte of bytes) target.push(byte);
}

export function makeZip(entries: Array<{ path: string; bytes: Uint8Array }>) {
  const encoder = new TextEncoder();
  const output: number[] = [];
  const centralDirectory: number[] = [];
  const uniqueEntries = Array.from(
    new Map(
      entries.map((entry) => {
        const portablePath = entry.path.replaceAll("\\", "/").replace(/^\/+/, "");
        return [portablePath, { ...entry, path: portablePath }];
      }),
    ).values(),
  );
  const utf8Flag = 0x0800;
  for (const entry of uniqueEntries) {
    const nameBytes = encoder.encode(entry.path);
    const offset = output.length;
    const crc = crc32(entry.bytes);
    writeUint32(output, 0x04034b50);
    writeUint16(output, 20);
    writeUint16(output, utf8Flag);
    writeUint16(output, 0);
    writeUint16(output, 0);
    writeUint16(output, 0);
    writeUint32(output, crc);
    writeUint32(output, entry.bytes.length);
    writeUint32(output, entry.bytes.length);
    writeUint16(output, nameBytes.length);
    writeUint16(output, 0);
    appendBytes(output, nameBytes);
    appendBytes(output, entry.bytes);

    writeUint32(centralDirectory, 0x02014b50);
    writeUint16(centralDirectory, 20);
    writeUint16(centralDirectory, 20);
    writeUint16(centralDirectory, utf8Flag);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint32(centralDirectory, crc);
    writeUint32(centralDirectory, entry.bytes.length);
    writeUint32(centralDirectory, entry.bytes.length);
    writeUint16(centralDirectory, nameBytes.length);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint32(centralDirectory, 0);
    writeUint32(centralDirectory, offset);
    appendBytes(centralDirectory, nameBytes);
  }
  const centralDirectoryOffset = output.length;
  output.push(...centralDirectory);
  writeUint32(output, 0x06054b50);
  writeUint16(output, 0);
  writeUint16(output, 0);
  writeUint16(output, uniqueEntries.length);
  writeUint16(output, uniqueEntries.length);
  writeUint32(output, centralDirectory.length);
  writeUint32(output, centralDirectoryOffset);
  writeUint16(output, 0);
  return new Blob([new Uint8Array(output)], { type: "application/zip" });
}
