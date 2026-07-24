using System;
using System.IO;
using System.Threading.Tasks;
using System.Web.Http;
using AdmissionAssistant.Core.Config;
using AdmissionAssistant.Web.Filters;

namespace AdmissionAssistant.Web.Controllers
{
    [ApiKeyAuthorize]
    [RoutePrefix("api/chat")]
    public class ChatController : ApiController
    {
        [HttpPost]
        [Route("")]
        public async Task<IHttpActionResult> Ask([FromBody] ChatRequest request)
        {
            if (request == null || string.IsNullOrWhiteSpace(request.Question))
                return BadRequest("Question is required.");

            var assistant = AdmissionAssistant.Web.Config.AssistantServiceFactory.Create(
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, AppSettings.VectorStorePath),
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, AppSettings.ProspectusStoragePath));

            var answer = await assistant.AskAsync(request.Question);
            return Ok(answer);
        }
    }

    public class ChatRequest
    {
        public string Question { get; set; }
    }
}
