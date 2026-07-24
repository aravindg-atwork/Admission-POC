using System.Linq;
using System.Text;
using System.Threading.Tasks;
using AdmissionAssistant.Core.Embeddings;
using AdmissionAssistant.Core.Llm;
using AdmissionAssistant.Core.VectorStore;

namespace AdmissionAssistant.Core.Rag
{
    public class RagService
    {
        private const string SystemPrompt =
            "You are a warm, friendly admissions assistant helping students with the B.V.Sc. & A.H. " +
            "program. Talk naturally and kindly, like a helpful counselor who wants the student to feel " +
            "at ease. When they ask about admissions, answer using ONLY the prospectus excerpts " +
            "provided and never invent details. If the excerpts don't cover something, say so gently and " +
            "point them to what you can help with. Weave page references into your answer naturally " +
            "(for example, 'you'll find this on page 9') rather than listing them mechanically. Keep " +
            "answers clear, encouraging, and easy for a nervous applicant to follow. " +
            "IMPORTANT: Reply in the SAME language and script the student used (Tamil to Tamil, Hindi to " +
            "Hindi, Marathi to Marathi, English to English). Write the way people actually speak that " +
            "language, keeping common English loanwords they used (like 'document', 'application', " +
            "'college') as-is in their script instead of forcing a formal translation. Never switch to a " +
            "different language than the student used, and never answer a real question with only a greeting.";

        private readonly IEmbeddingClient _embeddingClient;
        private readonly IVectorStore _vectorStore;
        private readonly IChatClient _chatClient;
        private readonly int _topK;

        public RagService(IEmbeddingClient embeddingClient, IVectorStore vectorStore, IChatClient chatClient, int topK = 5)
        {
            _embeddingClient = embeddingClient;
            _vectorStore = vectorStore;
            _chatClient = chatClient;
            _topK = topK;
        }

        public async Task<RagAnswer> AskAsync(string question)
        {
            var queryEmbedding = await _embeddingClient.EmbedAsync(question);
            var matches = _vectorStore.Search(queryEmbedding, _topK);

            var context = new StringBuilder();
            foreach (var match in matches)
            {
                context.AppendLine("[Page " + match.Chunk.PageNumber + "] " + match.Chunk.Text);
                context.AppendLine();
            }

            var userPrompt = "Prospectus excerpts:\n" + context + "\n\nQuestion: " + question;
            var answerText = await _chatClient.AskAsync(SystemPrompt, userPrompt);

            return new RagAnswer
            {
                AnswerText = answerText,
                PageReferences = matches.Select(m => m.Chunk.PageNumber).Distinct().OrderBy(p => p).ToList()
            };
        }
    }
}
