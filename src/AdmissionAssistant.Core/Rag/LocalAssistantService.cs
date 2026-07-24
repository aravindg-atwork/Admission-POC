using System.IO;
using System.Threading.Tasks;
using AdmissionAssistant.Core.Chunking;
using AdmissionAssistant.Core.Embeddings;
using AdmissionAssistant.Core.Ingestion;
using AdmissionAssistant.Core.Llm;
using AdmissionAssistant.Core.VectorStore;

namespace AdmissionAssistant.Core.Rag
{
    // Runs the whole pipeline in-process: chunking, retrieval and prompting are
    // plain C# you can step through. Only the embedding model is delegated to a
    // local HTTP call (embedding-service), since .NET 4.5 can't host it directly.
    public class LocalAssistantService : IAssistantService
    {
        private readonly IEmbeddingClient _embeddingClient;
        private readonly IVectorStore _vectorStore;
        private readonly string _prospectusStoragePath;
        private readonly RagService _ragService;

        public LocalAssistantService(
            IEmbeddingClient embeddingClient,
            IVectorStore vectorStore,
            IChatClient chatClient,
            string prospectusStoragePath)
        {
            _embeddingClient = embeddingClient;
            _vectorStore = vectorStore;
            _prospectusStoragePath = prospectusStoragePath;
            _ragService = new RagService(embeddingClient, vectorStore, chatClient);
        }

        public Task<RagAnswer> AskAsync(string question)
        {
            _vectorStore.Load();
            return _ragService.AskAsync(question);
        }

        public async Task<IngestResult> IngestAsync(Stream pdfStream, string fileName)
        {
            Directory.CreateDirectory(_prospectusStoragePath);
            var savedPath = Path.Combine(_prospectusStoragePath, "prospectus.pdf");

            using (var fileStream = File.Create(savedPath))
            {
                await pdfStream.CopyToAsync(fileStream);
            }

            var pages = new ProspectusPdfReader().ExtractPages(savedPath);
            var chunks = new TextChunker().Chunk(pages, "prospectus");

            _vectorStore.Clear();
            foreach (var chunk in chunks)
            {
                var embedding = await _embeddingClient.EmbedAsync(chunk.Text);
                _vectorStore.Add(chunk, embedding);
            }
            _vectorStore.Save();

            return new IngestResult { PagesProcessed = pages.Count, ChunksIndexed = chunks.Count };
        }
    }
}
