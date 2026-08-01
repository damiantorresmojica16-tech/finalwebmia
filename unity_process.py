#!/usr/bin/env python3
"""
Unity Asset Bundle processor for Free Fire files.
Handles LZ4HC compression to maintain near-identical file sizes.
Called from Node.js via child_process.

Usage:
  python3 unity_process.py <command> <input_file> <output_file> [args...]

Commands:
  list <input_file> <output_json>
      List all PathIDs and types in the bundle
  
  dump <input_file> <output_txt> <pathId>
      Export dump of a specific object
  
  compare <original_file> <modified_file> <output_json>
      Compare two files and output differences
  
  holo <input_file> <output_file> <mode> <oloColorHex> [borderColorHex] [wallColorHex]
      Apply hologram colors to materials
"""

import sys
import struct
import json
import os

try:
    import lz4.block
except ImportError:
    print("ERROR: lz4 not installed. Run: pip3 install lz4", file=sys.stderr)
    sys.exit(1)


CLASS_NAMES = {
    0: 'Object', 1: 'GameObject', 2: 'Component', 4: 'Transform',
    20: 'Camera', 21: 'Material', 23: 'MeshRenderer', 25: 'Renderer',
    28: 'Texture2D', 33: 'MeshFilter', 43: 'Mesh', 48: 'Shader',
    49: 'TextAsset', 54: 'Rigidbody', 65: 'BoxCollider',
    74: 'AnimationClip', 82: 'AudioSource', 83: 'AudioClip',
    84: 'RenderTexture', 89: 'Cubemap', 90: 'Avatar',
    91: 'AnimatorController', 95: 'Animator', 104: 'SpriteRenderer',
    111: 'Animation', 114: 'MonoBehaviour', 115: 'MonoScript',
    128: 'Font', 142: 'AssetBundle', 150: 'PreloadData',
    156: 'TerrainCollider', 157: 'TerrainData', 187: 'MeshCollider',
    198: 'ParticleSystem', 199: 'ParticleSystemRenderer',
    213: 'Sprite', 221: 'AnimatorOverrideController', 271: 'SpriteAtlas'
}


def align16(n):
    return ((n + 15) // 16) * 16


def align4(n):
    return ((n + 3) // 4) * 4


def read_cstring(data, offset):
    end = offset
    while end < len(data) and data[end] != 0:
        end += 1
    return data[offset:end].decode('utf-8', errors='replace'), end + 1


class UnityBundle:
    def __init__(self):
        self.raw = None
        self.header_end = 0
        self.data_start = 0
        self.flags = 0
        self.file_size_offset = 0
        self.ci_comp_size_offset = 0
        self.ci_uncomp_size = 0
        self.decompressed_info = None
        self.blocks = []
        self.nodes = []
        self.orig_comp_blocks = []
        self.decomp_blocks = []
        self.full_data = None
        self.objects = []
        self.types = []
        self.sf_data_offset = 0

    def load(self, data):
        self.raw = data
        offset = 0

        # Signature
        _, offset = read_cstring(data, offset)
        # Version
        offset += 4
        # Unity version
        _, offset = read_cstring(data, offset)
        # Generator version
        _, offset = read_cstring(data, offset)

        # File size
        self.file_size_offset = offset
        offset += 8

        # CI compressed size
        self.ci_comp_size_offset = offset
        ci_comp_size = struct.unpack('>I', data[offset:offset+4])[0]
        offset += 4

        # CI uncompressed size
        self.ci_uncomp_size = struct.unpack('>I', data[offset:offset+4])[0]
        offset += 4

        # Flags
        self.flags = struct.unpack('>I', data[offset:offset+4])[0]
        offset += 4

        # Padding
        if self.flags & 0x200:
            offset = align16(offset)
        self.header_end = offset

        # Block info
        block_info_raw = data[offset:offset + ci_comp_size]
        offset += ci_comp_size
        self.data_start = align16(offset)

        compression = self.flags & 0x3F
        if compression in (2, 3):
            self.decompressed_info = lz4.block.decompress(
                block_info_raw, uncompressed_size=self.ci_uncomp_size
            )
        else:
            self.decompressed_info = bytes(block_info_raw)

        # Parse block info
        info_off = 16  # skip hash
        block_count = struct.unpack('>I', self.decompressed_info[info_off:info_off+4])[0]
        info_off += 4

        self.blocks = []
        for _ in range(block_count):
            u_size = struct.unpack('>I', self.decompressed_info[info_off:info_off+4])[0]
            c_size = struct.unpack('>I', self.decompressed_info[info_off+4:info_off+8])[0]
            b_flags = struct.unpack('>H', self.decompressed_info[info_off+8:info_off+10])[0]
            info_off += 10
            self.blocks.append({'uSize': u_size, 'cSize': c_size, 'flags': b_flags})

        # Parse nodes
        node_count = struct.unpack('>I', self.decompressed_info[info_off:info_off+4])[0]
        info_off += 4
        self.nodes = []
        for _ in range(node_count):
            n_offset = struct.unpack('>Q', self.decompressed_info[info_off:info_off+8])[0]
            n_size = struct.unpack('>Q', self.decompressed_info[info_off+8:info_off+16])[0]
            n_flags = struct.unpack('>I', self.decompressed_info[info_off+16:info_off+20])[0]
            info_off += 20
            name, info_off = read_cstring(self.decompressed_info, info_off)
            self.nodes.append({'offset': n_offset, 'size': n_size, 'flags': n_flags, 'name': name})

        # Decompress data blocks
        comp_off = self.data_start
        self.orig_comp_blocks = []
        self.decomp_blocks = []
        for block in self.blocks:
            raw = data[comp_off:comp_off + block['cSize']]
            self.orig_comp_blocks.append(raw)
            comp_off += block['cSize']
            b_comp = block['flags'] & 0x3F
            if b_comp in (2, 3):
                decomp = lz4.block.decompress(raw, uncompressed_size=block['uSize'])
                self.decomp_blocks.append(decomp)
            else:
                self.decomp_blocks.append(bytes(raw))

        self.full_data = bytearray(b''.join(self.decomp_blocks))
        self._parse_serialized_file()

    def _parse_serialized_file(self):
        buf = self.full_data
        version = struct.unpack('>I', buf[8:12])[0]

        if version >= 22:
            self.sf_data_offset = struct.unpack('>Q', buf[32:40])[0]
        else:
            self.sf_data_offset = struct.unpack('>I', buf[12:16])[0]

        # Metadata starts at offset 48 for version 22
        offset = 48

        # Unity version string
        _, offset = read_cstring(buf, offset)

        # Platform (LE)
        offset += 4

        # Has type tree
        has_type_tree = buf[offset] != 0
        offset += 1

        # Types
        type_count = struct.unpack('<I', buf[offset:offset+4])[0]
        offset += 4

        self.types = []
        for _ in range(type_count):
            class_id = struct.unpack('<i', buf[offset:offset+4])[0]
            offset += 4
            offset += 1  # isStripped
            offset += 2  # scriptTypeIndex
            if class_id == 114:
                offset += 16  # script hash
            offset += 16  # type hash
            if has_type_tree:
                tree_node_count = struct.unpack('<I', buf[offset:offset+4])[0]
                offset += 4
                string_buf_size = struct.unpack('<I', buf[offset:offset+4])[0]
                offset += 4
                offset += tree_node_count * 32
                offset += string_buf_size
                if version >= 21:
                    ref_type_count = struct.unpack('<I', buf[offset:offset+4])[0]
                    offset += 4
                    for _ in range(ref_type_count):
                        offset += 4 + 16 + 16
                        rt_nodes = struct.unpack('<I', buf[offset:offset+4])[0]
                        offset += 4
                        rt_str_size = struct.unpack('<I', buf[offset:offset+4])[0]
                        offset += 4
                        offset += rt_nodes * 32 + rt_str_size
            self.types.append({'classId': class_id})

        # Objects
        object_count = struct.unpack('<I', buf[offset:offset+4])[0]
        offset += 4

        self.objects = []
        for _ in range(object_count):
            offset = align4(offset)
            path_id = struct.unpack('<q', buf[offset:offset+8])[0]
            offset += 8
            byte_start = struct.unpack('<Q', buf[offset:offset+8])[0]
            offset += 8
            byte_size = struct.unpack('<I', buf[offset:offset+4])[0]
            offset += 4
            type_id = struct.unpack('<I', buf[offset:offset+4])[0]
            offset += 4

            class_id = self.types[type_id]['classId'] if type_id < len(self.types) else -1
            abs_offset = self.sf_data_offset + byte_start

            self.objects.append({
                'pathId': str(path_id),
                'byteStart': byte_start,
                'byteSize': byte_size,
                'typeId': type_id,
                'classId': class_id,
                'absoluteOffset': abs_offset
            })

    def get_object_name(self, obj):
        try:
            off = obj['absoluteOffset']
            data = self.full_data[off:off + min(obj['byteSize'], 200)]
            if obj['classId'] in (21, 48, 142):
                name_len = struct.unpack('<I', data[0:4])[0]
                if 0 < name_len < 150:
                    return data[4:4+name_len].decode('utf-8', errors='replace')
        except:
            pass
        return ''

    def list_objects(self):
        result = []
        for obj in self.objects:
            result.append({
                'pathId': obj['pathId'],
                'typeName': CLASS_NAMES.get(obj['classId'], f"Type_{obj['classId']}"),
                'classId': obj['classId'],
                'size': obj['byteSize'],
                'name': self.get_object_name(obj)
            })
        return result

    def export_dump(self, path_id):
        obj = None
        for o in self.objects:
            if o['pathId'] == path_id:
                obj = o
                break
        if not obj:
            return f"Object not found: {path_id}"

        off = obj['absoluteOffset']
        obj_data = bytes(self.full_data[off:off + obj['byteSize']])
        lines = []
        lines.append(f"PathID: {obj['pathId']}")
        lines.append(f"Type: {CLASS_NAMES.get(obj['classId'], 'Type_' + str(obj['classId']))} (ClassID: {obj['classId']})")
        lines.append(f"Size: {obj['byteSize']} bytes")
        lines.append(f"Offset: {obj['absoluteOffset']}")
        lines.append('')

        if obj['classId'] == 21:
            lines.append('=== Material Properties ===')
            name = self.get_object_name(obj)
            if name:
                lines.append(f'Name: {name}')
            lines.append('')
            colors = self._find_colors(obj_data)
            if colors:
                lines.append('Colors:')
                for c in colors:
                    lines.append(f"  {c['name']}: RGBA({c['r']:.4f}, {c['g']:.4f}, {c['b']:.4f}, {c['a']:.4f})")
            floats = self._find_floats(obj_data)
            if floats:
                lines.append('\nFloats:')
                for f in floats:
                    lines.append(f"  {f['name']}: {f['value']:.6f}")
        else:
            lines.append('=== Hex Dump ===')
            max_bytes = min(len(obj_data), 512)
            for i in range(0, max_bytes, 16):
                chunk = obj_data[i:min(i+16, max_bytes)]
                hex_str = ' '.join(f'{b:02x}' for b in chunk)
                ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                lines.append(f"{i:08x}: {hex_str:<48} {ascii_str}")
            if len(obj_data) > 512:
                lines.append(f"... ({len(obj_data) - 512} more bytes)")

        return '\n'.join(lines)

    def _find_colors(self, data):
        colors = []
        i = 0
        while i < len(data) - 24:
            if i + 4 > len(data):
                break
            possible_len = struct.unpack('<I', data[i:i+4])[0]
            if possible_len < 3 or possible_len > 50 or i + 4 + possible_len > len(data):
                i += 1
                continue
            if data[i+4] != 0x5F:  # must start with '_'
                i += 1
                continue

            valid = True
            for j in range(possible_len):
                c = data[i + 4 + j]
                if c < 32 or c > 126:
                    valid = False
                    break
            if not valid:
                i += 1
                continue

            name = data[i+4:i+4+possible_len].decode('utf-8', errors='replace')
            after_name = i + 4 + possible_len
            aligned = align4(after_name)

            if aligned + 16 > len(data):
                i += 1
                continue

            f1, f2, f3, f4 = struct.unpack('<ffff', data[aligned:aligned+16])

            is_color = ('color' in name.lower() or 'col' in name.lower() or
                       name in ('_Insten', '_RimColor', '_CharaSpectatorColor'))

            if is_color and all(abs(v) <= 100 and v == v for v in (f1, f2, f3, f4)):
                colors.append({
                    'name': name,
                    'r': f1, 'g': f2, 'b': f3, 'a': f4,
                    '_offset': aligned  # offset within obj_data
                })
            i = i + 4 + possible_len
        return colors

    def _find_floats(self, data):
        floats = []
        i = 0
        while i < len(data) - 12:
            if i + 4 > len(data):
                break
            possible_len = struct.unpack('<I', data[i:i+4])[0]
            if possible_len < 3 or possible_len > 50 or i + 4 + possible_len > len(data):
                i += 1
                continue
            if data[i+4] != 0x5F:
                i += 1
                continue

            valid = True
            for j in range(possible_len):
                c = data[i + 4 + j]
                if c < 32 or c > 126:
                    valid = False
                    break
            if not valid:
                i += 1
                continue

            name = data[i+4:i+4+possible_len].decode('utf-8', errors='replace')
            after_name = i + 4 + possible_len
            aligned = align4(after_name)

            if aligned + 4 > len(data):
                i += 1
                continue

            skip = ('color' in name.lower() or 'col' in name.lower() or
                   'tex' in name.lower() or 'map' in name.lower())
            if skip:
                i = i + 4 + possible_len
                continue

            val = struct.unpack('<f', data[aligned:aligned+4])[0]
            if val == val and abs(val) <= 10000:  # not NaN and reasonable
                floats.append({'name': name, 'value': val})
            i = i + 4 + possible_len
        return floats

    def modify_colors(self, mode, olo_hex, border_hex=None, wall_hex=None):
        """Modify material colors and return the modified file buffer."""
        olo_color = hex_to_rgba(olo_hex)
        border_color = hex_to_rgba(border_hex) if border_hex else None
        wall_color = hex_to_rgba(wall_hex) if wall_hex else None

        materials = [o for o in self.objects if o['classId'] == 21]
        affected_blocks = set()

        for mat in materials:
            off = mat['absoluteOffset']
            mat_data = bytes(self.full_data[off:off + mat['byteSize']])
            colors = self._find_colors(mat_data)

            for color_prop in colors:
                abs_offset = off + color_prop['_offset']

                if mode == 'bordes':
                    if border_color and ('Rim' in color_prop['name'] or 'Spectator' in color_prop['name']):
                        new_color = border_color
                    else:
                        new_color = olo_color
                else:
                    new_color = olo_color

                if wall_color and 'Spectator' in color_prop['name']:
                    new_color = wall_color

                # Write new color to full_data
                struct.pack_into('<ffff', self.full_data, abs_offset,
                               new_color['r'], new_color['g'], new_color['b'], new_color['a'])

                # Track which block this belongs to
                cum_size = 0
                for bi, block in enumerate(self.blocks):
                    if abs_offset >= cum_size and abs_offset < cum_size + block['uSize']:
                        affected_blocks.add(bi)
                        break
                    cum_size += block['uSize']

        if not affected_blocks:
            return bytes(self.raw)

        # Recompress affected blocks with LZ4HC
        new_comp_blocks = []
        new_block_sizes = []
        cum_size = 0

        for i, block in enumerate(self.blocks):
            if i in affected_blocks:
                block_data = bytes(self.full_data[cum_size:cum_size + block['uSize']])
                b_comp = block['flags'] & 0x3F
                if b_comp in (2, 3):
                    recompressed = lz4.block.compress(
                        block_data, mode='high_compression',
                        compression=12, store_size=False
                    )
                    new_comp_blocks.append(recompressed)
                    new_block_sizes.append(len(recompressed))
                else:
                    new_comp_blocks.append(block_data)
                    new_block_sizes.append(len(block_data))
            else:
                new_comp_blocks.append(self.orig_comp_blocks[i])
                new_block_sizes.append(block['cSize'])
            cum_size += block['uSize']

        # Rebuild block info with new sizes
        new_info = bytearray(self.decompressed_info)
        info_off = 16 + 4  # skip hash + block count
        for i in range(len(self.blocks)):
            # uSize stays the same (offset +0)
            struct.pack_into('>I', new_info, info_off + 4, new_block_sizes[i])
            info_off += 10

        # Recompress block info
        compression = self.flags & 0x3F
        if compression in (2, 3):
            new_comp_info = lz4.block.compress(
                bytes(new_info), mode='high_compression',
                compression=12, store_size=False
            )
        else:
            new_comp_info = bytes(new_info)

        # Rebuild file
        new_data_start = align16(self.header_end + len(new_comp_info))
        total_comp_data = sum(new_block_sizes)
        total_file_size = new_data_start + total_comp_data

        output = bytearray(total_file_size)
        # Copy original header
        output[:self.header_end] = self.raw[:self.header_end]

        # Update file size
        struct.pack_into('>Q', output, self.file_size_offset, total_file_size)
        # Update compressed info size
        struct.pack_into('>I', output, self.ci_comp_size_offset, len(new_comp_info))

        # Write block info
        output[self.header_end:self.header_end + len(new_comp_info)] = new_comp_info

        # Write data blocks
        write_off = new_data_start
        for block_data in new_comp_blocks:
            output[write_off:write_off + len(block_data)] = block_data
            write_off += len(block_data)

        return bytes(output)


def hex_to_rgba(hex_str):
    hex_str = hex_str.lstrip('#')
    r = int(hex_str[0:2], 16) / 255.0
    g = int(hex_str[2:4], 16) / 255.0
    b = int(hex_str[4:6], 16) / 255.0
    a = 1.0
    return {'r': r, 'g': g, 'b': b, 'a': a}


def compare_bundles(orig_data, mod_data):
    orig = UnityBundle()
    orig.load(orig_data)
    mod = UnityBundle()
    mod.load(mod_data)

    differences = []
    for orig_obj in orig.objects:
        mod_obj = None
        for o in mod.objects:
            if o['pathId'] == orig_obj['pathId']:
                mod_obj = o
                break
        if not mod_obj:
            continue

        orig_obj_data = bytes(orig.full_data[orig_obj['absoluteOffset']:orig_obj['absoluteOffset'] + orig_obj['byteSize']])
        mod_obj_data = bytes(mod.full_data[mod_obj['absoluteOffset']:mod_obj['absoluteOffset'] + mod_obj['byteSize']])

        if orig_obj_data != mod_obj_data:
            dump_text = f"PathID: {orig_obj['pathId']}\nType: {CLASS_NAMES.get(orig_obj['classId'], 'Type_' + str(orig_obj['classId']))}\n"

            if orig_obj['classId'] == 21:
                orig_colors = orig._find_colors(orig_obj_data)
                mod_colors = mod._find_colors(mod_obj_data)
                for i, oc in enumerate(orig_colors):
                    if i < len(mod_colors):
                        mc = mod_colors[i]
                        if oc['r'] != mc['r'] or oc['g'] != mc['g'] or oc['b'] != mc['b'] or oc['a'] != mc['a']:
                            dump_text += f"\n{oc['name']}:\n"
                            dump_text += f"  Original: RGBA({oc['r']:.4f}, {oc['g']:.4f}, {oc['b']:.4f}, {oc['a']:.4f})\n"
                            dump_text += f"  Modified: RGBA({mc['r']:.4f}, {mc['g']:.4f}, {mc['b']:.4f}, {mc['a']:.4f})\n"

            differences.append({
                'pathId': orig_obj['pathId'],
                'typeName': CLASS_NAMES.get(orig_obj['classId'], f"Type_{orig_obj['classId']}"),
                'dumpText': dump_text
            })

    return differences


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 unity_process.py <command> <args...>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'list':
        input_file = sys.argv[2]
        output_file = sys.argv[3]
        with open(input_file, 'rb') as f:
            data = f.read()
        bundle = UnityBundle()
        bundle.load(data)
        result = bundle.list_objects()
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False)

    elif command == 'dump':
        input_file = sys.argv[2]
        output_file = sys.argv[3]
        path_id = sys.argv[4]
        with open(input_file, 'rb') as f:
            data = f.read()
        bundle = UnityBundle()
        bundle.load(data)
        dump = bundle.export_dump(path_id)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(dump)

    elif command == 'compare':
        orig_file = sys.argv[2]
        mod_file = sys.argv[3]
        output_file = sys.argv[4]
        with open(orig_file, 'rb') as f:
            orig_data = f.read()
        with open(mod_file, 'rb') as f:
            mod_data = f.read()
        diffs = compare_bundles(orig_data, mod_data)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(diffs, f, ensure_ascii=False)

    elif command == 'holo':
        input_file = sys.argv[2]
        output_file = sys.argv[3]
        mode = sys.argv[4]
        olo_hex = sys.argv[5]
        border_hex = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] != 'null' else None
        wall_hex = sys.argv[7] if len(sys.argv) > 7 and sys.argv[7] != 'null' else None

        with open(input_file, 'rb') as f:
            data = f.read()
        bundle = UnityBundle()
        bundle.load(data)
        modified = bundle.modify_colors(mode, olo_hex, border_hex, wall_hex)
        with open(output_file, 'wb') as f:
            f.write(modified)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
