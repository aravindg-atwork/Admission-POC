using System.Collections.Generic;

namespace AdmissionAssistant.Core.Chunking
{
    // Sliding-window chunker over page-extracted text. Keeps a page number on every
    // chunk so answers can cite the prospectus page they came from.
    public class TextChunker
    {
        private readonly int _maxChunkChars;
        private readonly int _overlapChars;

        public TextChunker(int maxChunkChars = 1200, int overlapChars = 200)
        {
            _maxChunkChars = maxChunkChars;
            _overlapChars = overlapChars;
        }

        public List<Chunk> Chunk(IEnumerable<PageText> pages, string sourceDocument)
        {
            var chunks = new List<Chunk>();
            var chunkIndex = 0;

            foreach (var page in pages)
            {
                var text = page.Text?.Trim() ?? string.Empty;
                if (text.Length == 0) continue;

                var start = 0;
                while (start < text.Length)
                {
                    var length = System.Math.Min(_maxChunkChars, text.Length - start);
                    var slice = text.Substring(start, length);

                    chunks.Add(new Chunk
                    {
                        Id = sourceDocument + "-" + chunkIndex++,
                        Text = slice,
                        PageNumber = page.PageNumber,
                        SourceDocument = sourceDocument
                    });

                    if (start + length >= text.Length) break;
                    start += _maxChunkChars - _overlapChars;
                }
            }

            return chunks;
        }
    }
}
