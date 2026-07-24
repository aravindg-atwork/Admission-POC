using System.Collections.Generic;
using System.Text;
using iTextSharp.text.pdf;
using AdmissionAssistant.Core.Chunking;
using PdfTextExtractor = iTextSharp.text.pdf.parser.PdfTextExtractor;

namespace AdmissionAssistant.Core.Ingestion
{
    // Page-aware PDF text extraction via iTextSharp, the one PDF library that still
    // reliably targets .NET Framework 4.5 (modern alternatives require .NET Standard).
    public class ProspectusPdfReader
    {
        public List<PageText> ExtractPages(string pdfPath)
        {
            var pages = new List<PageText>();

            using (var reader = new PdfReader(pdfPath))
            {
                for (var i = 1; i <= reader.NumberOfPages; i++)
                {
                    var text = PdfTextExtractor.GetTextFromPage(reader, i);
                    pages.Add(new PageText { PageNumber = i, Text = CleanText(text) });
                }
            }

            return pages;
        }

        private static string CleanText(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return string.Empty;

            var sb = new StringBuilder();
            var lastWasSpace = false;

            foreach (var c in raw)
            {
                if (char.IsWhiteSpace(c))
                {
                    if (!lastWasSpace) sb.Append(' ');
                    lastWasSpace = true;
                }
                else
                {
                    sb.Append(c);
                    lastWasSpace = false;
                }
            }

            return sb.ToString().Trim();
        }
    }
}
