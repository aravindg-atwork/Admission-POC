using System;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace AdmissionAssistant.Core.Rag
{
    // Forwards to an external service implementing the same /api/chat and
    // /api/ingest contract as this app's own Web API. Lets the whole pipeline be
    // swapped for a standalone microservice (e.g. a fuller Python implementation)
    // by flipping AssistantMode in Web.config — no controller changes needed.
    public class RemoteAssistantService : IAssistantService
    {
        private readonly HttpClient _httpClient;
        private readonly string _baseUrl;

        public RemoteAssistantService(string baseUrl, HttpClient httpClient = null)
        {
            _baseUrl = baseUrl.TrimEnd('/');
            _httpClient = httpClient ?? new HttpClient();
        }

        public async Task<RagAnswer> AskAsync(string question)
        {
            var payload = JsonConvert.SerializeObject(new { question });
            var content = new StringContent(payload, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync(_baseUrl + "/api/chat", content);
            response.EnsureSuccessStatusCode();

            var body = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<RagAnswer>(body);
        }

        public async Task<IngestResult> IngestAsync(Stream pdfStream, string fileName)
        {
            using (var form = new MultipartFormDataContent())
            {
                var fileContent = new StreamContent(pdfStream);
                fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
                form.Add(fileContent, "file", fileName);

                var response = await _httpClient.PostAsync(_baseUrl + "/api/ingest", form);
                response.EnsureSuccessStatusCode();

                var body = await response.Content.ReadAsStringAsync();
                return JsonConvert.DeserializeObject<IngestResult>(body);
            }
        }
    }
}
