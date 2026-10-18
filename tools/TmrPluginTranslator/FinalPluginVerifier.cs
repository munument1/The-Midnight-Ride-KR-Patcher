using System.Buffers.Binary;
using System.IO.Compression;
using System.Text;

// Independent final-file comparison, after both text editing and index removal.
internal static class FinalPluginVerifier
{
    internal sealed record Result(int TextChanges, int OFST, int CLSZ, int ProtectedRecords);
    private sealed record Chunk(string Signature, uint Form, uint Flags, int Depth, byte[] Header, byte[] Body);
    private sealed record Field(string Signature, byte[] Value, byte[] Raw);
    private static readonly Encoding Utf8 = new UTF8Encoding(false, true);

    public static Result Verify(string source, string output,
        IEnumerable<OriginalTextWriter.Pair> mappings, int expectedChanges)
    {
        var before = Read(source);
        var after = Read(output);
        if (before.Count != after.Count) throw new InvalidDataException("Final record/group count changed");
        var allowed = mappings.Select(p => p with {
            Source = Normalize(p.Source), Dest = Normalize(p.Dest) }).ToHashSet();
        var masters = Fields(Decode(before[0])).Where(f => f.Signature == "MAST")
            .Select(f => Text(f.Value)).Append(Path.GetFileName(source)).ToArray();
        int changed = 0, ofst = 0, clsz = 0, protectedCount = 0;
        for (int i = 0; i < before.Count; i++)
        {
            var a = before[i]; var b = after[i];
            if (a.Depth != b.Depth || !a.Header.AsSpan(0, 4).SequenceEqual(b.Header.AsSpan(0, 4))
                || !a.Header.AsSpan(8).SequenceEqual(b.Header.AsSpan(8)))
                throw new InvalidDataException($"Final header/order/parent changed: {a.Signature}:{a.Form:X8}");
            if (a.Signature == "GRUP") continue;
            var decoded = Decode(a);
            var originalFields = Fields(decoded);
            var index = a.Form >> 24;
            var isProtected = (index < masters.Length
                && masters[index].Equals("Fallout4.esm", StringComparison.OrdinalIgnoreCase)
                && (a.Form & 0xFFFFFF) is 0x055402 or 0x02495A or 0x00DCEC)
                || originalFields.Any(f => f.Signature == "EDID"
                    && Text(f.Value).Contains("Zimonja", StringComparison.OrdinalIgnoreCase));
            if (isProtected)
            {
                protectedCount++;
                if (!a.Header.SequenceEqual(b.Header) || !a.Body.SequenceEqual(b.Body))
                    throw new InvalidDataException($"Protected Zimonja bytes changed: {a.Signature}:{a.Form:X8}");
            }
            var expected = new List<Field>();
            foreach (var field in originalFields)
            {
                if (a.Signature == "WRLD" && field.Signature is "OFST" or "CLSZ")
                {
                    if (field.Signature == "OFST") ofst++; else clsz++;
                }
                else expected.Add(field);
            }
            var actual = Fields(Decode(b));
            if (expected.Count != actual.Count)
                throw new InvalidDataException($"Final field count changed: {a.Signature}:{a.Form:X8}");
            for (int j = 0; j < expected.Count; j++)
            {
                var old = expected[j]; var current = actual[j];
                if (old.Signature != current.Signature)
                    throw new InvalidDataException("Final field order changed");
                if (old.Raw.SequenceEqual(current.Raw)) continue;
                if (old.Value.SequenceEqual(current.Value))
                    throw new InvalidDataException("Untouched field header/XXXX changed");
                var dest = Text(current.Value, strictUtf8: true);
                if (!allowed.Contains(new OriginalTextWriter.Pair(a.Signature, old.Signature,
                    Normalize(Text(old.Value)), Normalize(dest))))
                    throw new InvalidDataException($"Final non-text/unmapped change: {a.Signature}:{a.Form:X8}:{old.Signature}");
                changed++;
            }
            if (decoded.SequenceEqual(Decode(b)) && !a.Body.SequenceEqual(b.Body))
                throw new InvalidDataException("Untouched compressed record changed");
        }
        if (changed != expectedChanges)
            throw new InvalidDataException($"Final text count mismatch: {changed} != {expectedChanges}");
        WorldIndexStripper.ValidateInput(output);
        return new Result(changed, ofst, clsz, protectedCount);
    }

    private static string Normalize(string text) => text.Replace("\r\n", "\n");
    private static string Text(byte[] bytes, bool strictUtf8 = false)
    {
        if (bytes.Length == 0 || bytes[^1] != 0 || bytes.AsSpan(0, bytes.Length - 1).Contains((byte)0))
            throw new InvalidDataException("Expected complete display string");
        try { return Utf8.GetString(bytes, 0, bytes.Length - 1); }
        catch (DecoderFallbackException) when (!strictUtf8)
        { return Encoding.GetEncoding(1252).GetString(bytes, 0, bytes.Length - 1); }
    }

    private static byte[] Decode(Chunk chunk)
    {
        if ((chunk.Flags & 0x40000) == 0) return chunk.Body;
        if (chunk.Body.Length < 4) throw new InvalidDataException("Truncated compressed record");
        using var stream = new MemoryStream(chunk.Body, 4, chunk.Body.Length - 4);
        using var compressed = new ZLibStream(stream, CompressionMode.Decompress);
        using var decoded = new MemoryStream(); compressed.CopyTo(decoded);
        if (decoded.Length != BinaryPrimitives.ReadUInt32LittleEndian(chunk.Body))
            throw new InvalidDataException("Final decompressed size mismatch");
        return decoded.ToArray();
    }

    private static List<Chunk> Read(string path)
    {
        var data = File.ReadAllBytes(path);
        var result = new List<Chunk>();
        var seen = new HashSet<(string, uint)>();
        Walk(data, 0, data.Length, 0, result, seen);
        if (result.Count == 0 || result[0].Signature != "TES4")
            throw new InvalidDataException("Missing final TES4 header");
        return result;
    }

    private static void Walk(byte[] data, int start, int end, int depth,
        List<Chunk> result, HashSet<(string, uint)> seen)
    {
        if (depth > 64) throw new InvalidDataException("Excessive nesting");
        for (int pos = start; pos < end;)
        {
            if (end - pos < 24) throw new InvalidDataException("Truncated final header");
            var header = data.AsSpan(pos, 24).ToArray();
            var sig = Encoding.ASCII.GetString(header, 0, 4);
            var size = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(4)));
            var flags = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(8));
            var form = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(12));
            if (sig == "GRUP")
            {
                if (size < 24 || size > end - pos) throw new InvalidDataException("Invalid final group boundary");
                result.Add(new Chunk(sig, form, flags, depth, header, Array.Empty<byte>()));
                Walk(data, pos + 24, pos + size, depth + 1, result, seen);
                pos += size;
            }
            else
            {
                if (size > end - pos - 24 || !seen.Add((sig, form)))
                    throw new InvalidDataException("Invalid/duplicate final record");
                result.Add(new Chunk(sig, form, flags, depth, header, data.AsSpan(pos + 24, size).ToArray()));
                pos += 24 + size;
            }
        }
    }

    private static List<Field> Fields(byte[] body)
    {
        var result = new List<Field>();
        for (int pos = 0; pos < body.Length;)
        {
            int start = pos;
            if (body.Length - pos < 6) throw new InvalidDataException("Truncated final field");
            var sig = Encoding.ASCII.GetString(body, pos, 4);
            uint size = BinaryPrimitives.ReadUInt16LittleEndian(body.AsSpan(pos + 4)); pos += 6;
            if (sig == "XXXX")
            {
                if (size != 4 || body.Length - pos < 10) throw new InvalidDataException("Invalid final XXXX");
                size = BinaryPrimitives.ReadUInt32LittleEndian(body.AsSpan(pos));
                sig = Encoding.ASCII.GetString(body, pos + 4, 4); pos += 10;
                if (sig == "XXXX") throw new InvalidDataException("Repeated final XXXX");
            }
            if (size > body.Length - pos) throw new InvalidDataException("Invalid final field size");
            var value = body.AsSpan(pos, checked((int)size)).ToArray(); pos += checked((int)size);
            result.Add(new Field(sig, value, body.AsSpan(start, pos - start).ToArray()));
        }
        return result;
    }
}
