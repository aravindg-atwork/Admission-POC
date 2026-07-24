using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace AdmissionAssistant.Core.Embeddings
{
    // Calls the local embedding-service (Python, HuggingFace "nomic-embed-text") over HTTP.
    // .NET Framework 4.5 has no supported way to run HuggingFace models in-process, so
    // embedding generation is delegated to services/embedding-service.
    public class NomicEmbeddingClient : IEmbeddingClient
    {
        private readonly HttpClient _httpClient;
        private readonly string _baseUrl;

        public NomicEmbeddingClient(string baseUrl, string apiKey = null, HttpClient httpClient = null)
        {
            _baseUrl = baseUrl.TrimEnd('/');
            _httpClient = httpClient ?? new HttpClient();

            if (!string.IsNullOrEmpty(apiKey))
                _httpClient.DefaultRequestHeaders.Add("X-API-Key", apiKey);
        }

        public async Task<float[]> EmbedAsync(string text)
        {
            var result = await EmbedBatchAsync(new[] { text });
            return result.First();
        }

        public async Task<List<float[]>> EmbedBatchAsync(IEnumerable<string> texts)
        {
            var payload = JsonConvert.SerializeObject(new { texts = texts.ToArray() });
            var content = new StringContent(payload, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync(_baseUrl + "/embed", content);
            response.EnsureSuccessStatusCode();

            var body = await response.Content.ReadAsStringAsync();
            var parsed = JsonConvert.DeserializeObject<EmbedResponse>(body);
            return parsed.Embeddings;
        }

        private class EmbedResponse
        {
            public List<float[]> Embeddings { get; set; }
        }
    }
}
