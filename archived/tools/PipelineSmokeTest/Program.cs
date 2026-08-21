using System;
using System.IO;
using System.Linq;
using AdmissionAssistant.Core.Embeddings;
using AdmissionAssistant.Core.Llm;
using AdmissionAssistant.Core.Rag;
using AdmissionAssistant.Core.VectorStore;

namespace PipelineSmokeTest
{
    // WebForms can't run on this dev machine (no VS / IIS Express), so this exercises
    // the real Core pipeline directly: ingest a prospectus PDF, then ask it questions,
    // exactly what ChatController/IngestController do at runtime.
    internal static class Program
    {
        private static void Main(string[] args)
        {
            var opts = Options.Parse(args);

            Console.WriteLine("Embedding service : " + opts.EmbeddingServiceUrl);
            Console.WriteLine("Ollama            : " + opts.OllamaBaseUrl + " (" + opts.OllamaModel + ")");
            Console.WriteLine("Prospectus        : " + opts.PdfPath);
            Console.WriteLine();

            var embeddingClient = new NomicEmbeddingClient(opts.EmbeddingServiceUrl, opts.EmbeddingServiceApiKey);
            var vectorStore = new JsonVectorStore(opts.VectorStorePath);
            var chatClient = new OllamaChatClient(opts.OllamaBaseUrl, opts.OllamaModel);
            var assistant = new LocalAssistantService(embeddingClient, vectorStore, chatClient, opts.ProspectusDir);

            Console.WriteLine("--- Ingesting ---");
            using (var pdfStream = File.OpenRead(opts.PdfPath))
            {
                var result = assistant.IngestAsync(pdfStream, Path.GetFileName(opts.PdfPath)).GetAwaiter().GetResult();
                Console.WriteLine("Pages processed : " + result.PagesProcessed);
                Console.WriteLine("Chunks indexed  : " + result.ChunksIndexed);
            }

            Console.WriteLine();

            foreach (var question in opts.Questions)
            {
                Console.WriteLine("--- Q: " + question + " ---");
                var answer = assistant.AskAsync(question).GetAwaiter().GetResult();
                Console.WriteLine("A: " + answer.AnswerText);
                Console.WriteLine("Pages: " + string.Join(", ", answer.PageReferences));
                Console.WriteLine();
            }
        }
    }

    internal class Options
    {
        public string PdfPath;
        public string EmbeddingServiceUrl = "http://localhost:8000";
        public string EmbeddingServiceApiKey;
        public string OllamaBaseUrl = "http://localhost:11434";
        public string OllamaModel = "llama3.1";
        public string VectorStorePath = "vector-store.json";
        public string ProspectusDir = "prospectus";
        public string[] Questions = new string[0];

        public static Options Parse(string[] args)
        {
            var opts = new Options();
            var questions = new System.Collections.Generic.List<string>();

            for (var i = 0; i < args.Length; i++)
            {
                switch (args[i])
                {
                    case "--pdf": opts.PdfPath = args[++i]; break;
                    case "--embed-url": opts.EmbeddingServiceUrl = args[++i]; break;
                    case "--embed-key": opts.EmbeddingServiceApiKey = args[++i]; break;
                    case "--ollama-url": opts.OllamaBaseUrl = args[++i]; break;
                    case "--ollama-model": opts.OllamaModel = args[++i]; break;
                    case "--store": opts.VectorStorePath = args[++i]; break;
                    case "--q": questions.Add(args[++i]); break;
                }
            }

            if (string.IsNullOrEmpty(opts.PdfPath))
                throw new ArgumentException("--pdf <path> is required");

            opts.Questions = questions.ToArray();
            return opts;
        }
    }
}
