using System;
using AdmissionAssistant.Core.Config;
using AdmissionAssistant.Core.Embeddings;
using AdmissionAssistant.Core.Llm;
using AdmissionAssistant.Core.Rag;
using AdmissionAssistant.Core.VectorStore;

namespace AdmissionAssistant.Web.Config
{
    // Reads AssistantMode from Web.config ("Local" | "Remote") and builds the
    // matching IAssistantService. Controllers depend only on the interface, so
    // switching modes is a config change, not a code change.
    public static class AssistantServiceFactory
    {
        public static IAssistantService Create(string vectorStorePath, string prospectusStoragePath)
        {
            if (string.Equals(AppSettings.AssistantMode, "Remote", StringComparison.OrdinalIgnoreCase))
            {
                return new RemoteAssistantService(AppSettings.RemoteAssistantServiceUrl);
            }

            var embeddingClient = new NomicEmbeddingClient(AppSettings.EmbeddingServiceUrl, AppSettings.EmbeddingServiceApiKey);
            var vectorStore = new JsonVectorStore(vectorStorePath);

            IChatClient chatClient = string.Equals(AppSettings.ChatProvider, "Claude", StringComparison.OrdinalIgnoreCase)
                ? (IChatClient)new ClaudeChatClient(AppSettings.ClaudeApiKey, AppSettings.ClaudeModel)
                : new OllamaChatClient(AppSettings.OllamaBaseUrl, AppSettings.OllamaModel);

            return new LocalAssistantService(embeddingClient, vectorStore, chatClient, prospectusStoragePath);
        }
    }
}
