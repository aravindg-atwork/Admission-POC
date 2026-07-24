using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AdmissionAssistant.Core.Llm
{
    // No official Anthropic SDK targets .NET Framework 4.5, so this calls the
    // Messages API directly over HttpClient (built into .NET 4.5).
    public class ClaudeChatClient : IChatClient
    {
        private const string ApiUrl = "https://api.anthropic.com/v1/messages";
        private readonly HttpClient _httpClient;
        private readonly string _model;

        public ClaudeChatClient(string apiKey, string model = "claude-sonnet-5", HttpClient httpClient = null)
        {
            _model = model;
            _httpClient = httpClient ?? new HttpClient();
            _httpClient.DefaultRequestHeaders.Add("x-api-key", apiKey);
            _httpClient.DefaultRequestHeaders.Add("anthropic-version", "2023-06-01");
        }

        public async Task<string> AskAsync(string systemPrompt, string userPrompt)
        {
            var payload = new
            {
                model = _model,
                max_tokens = 1024,
                system = systemPrompt,
                messages = new[]
                {
                    new { role = "user", content = userPrompt }
                }
            };

            var content = new StringContent(JsonConvert.SerializeObject(payload), Encoding.UTF8, "application/json");
            var response = await _httpClient.PostAsync(ApiUrl, content);
            response.EnsureSuccessStatusCode();

            var body = await response.Content.ReadAsStringAsync();
            var parsed = JObject.Parse(body);
            return parsed["content"][0]["text"].ToString();
        }
    }
}
