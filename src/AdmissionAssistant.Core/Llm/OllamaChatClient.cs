using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AdmissionAssistant.Core.Llm
{
    // Calls a local Ollama instance (https://ollama.com) running an open-source model —
    // zero API cost and no account/billing, which is what "no paid APIs" for a POC
    // actually requires. Ollama exposes a REST API on localhost, so this is just
    // another HttpClient call, the same shape as ClaudeChatClient.
    public class OllamaChatClient : IChatClient
    {
        private readonly HttpClient _httpClient;
        private readonly string _baseUrl;
        private readonly string _model;

        public OllamaChatClient(string baseUrl, string model, HttpClient httpClient = null)
        {
            _baseUrl = baseUrl.TrimEnd('/');
            _model = model;
            _httpClient = httpClient ?? new HttpClient();
        }

        public async Task<string> AskAsync(string systemPrompt, string userPrompt)
        {
            var payload = new
            {
                model = _model,
                stream = false,
                messages = new[]
                {
                    new { role = "system", content = systemPrompt },
                    new { role = "user", content = userPrompt }
                }
            };

            var content = new StringContent(JsonConvert.SerializeObject(payload), Encoding.UTF8, "application/json");
            var response = await _httpClient.PostAsync(_baseUrl + "/api/chat", content);
            response.EnsureSuccessStatusCode();

            var body = await response.Content.ReadAsStringAsync();
            var parsed = JObject.Parse(body);
            return parsed["message"]["content"].ToString();
        }
    }
}
