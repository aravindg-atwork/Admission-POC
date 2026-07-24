using System.Configuration;

namespace AdmissionAssistant.Core.Config
{
    public static class AppSettings
    {
        public static string ChatProvider => ConfigurationManager.AppSettings["ChatProvider"] ?? "Ollama";
        public static string ClaudeApiKey => ConfigurationManager.AppSettings["ClaudeApiKey"];
        public static string ClaudeModel => ConfigurationManager.AppSettings["ClaudeModel"] ?? "claude-sonnet-5";
        public static string OllamaBaseUrl => ConfigurationManager.AppSettings["OllamaBaseUrl"] ?? "http://localhost:11434";
        public static string OllamaModel => ConfigurationManager.AppSettings["OllamaModel"] ?? "llama3.1";
        public static string EmbeddingServiceUrl => ConfigurationManager.AppSettings["EmbeddingServiceUrl"] ?? "http://localhost:8000";
        public static string EmbeddingServiceApiKey => ConfigurationManager.AppSettings["EmbeddingServiceApiKey"];
        public static string VectorStorePath => ConfigurationManager.AppSettings["VectorStorePath"] ?? "App_Data/vector-store.json";
        public static string ProspectusStoragePath => ConfigurationManager.AppSettings["ProspectusStoragePath"] ?? "App_Data/prospectus";
        public static string AssistantMode => ConfigurationManager.AppSettings["AssistantMode"] ?? "Local";
        public static string RemoteAssistantServiceUrl => ConfigurationManager.AppSettings["RemoteAssistantServiceUrl"] ?? "http://localhost:9000";
        public static string ApiKeysPath => ConfigurationManager.AppSettings["ApiKeysPath"] ?? "App_Data/api-keys.json";
        public static string AdminToken => ConfigurationManager.AppSettings["AdminToken"];
        public static string DefaultApiKeyLabel => ConfigurationManager.AppSettings["DefaultApiKeyLabel"] ?? "admission-site";
    }
}
