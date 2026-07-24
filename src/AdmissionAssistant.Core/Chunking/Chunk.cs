namespace AdmissionAssistant.Core.Chunking
{
    public class Chunk
    {
        public string Id { get; set; }
        public string Text { get; set; }
        public int PageNumber { get; set; }
        public string SourceDocument { get; set; }
    }

    public class PageText
    {
        public int PageNumber { get; set; }
        public string Text { get; set; }
    }
}
