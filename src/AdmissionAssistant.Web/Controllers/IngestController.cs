using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Threading.Tasks;
using System.Web.Http;
using AdmissionAssistant.Core.Config;
using AdmissionAssistant.Web.Filters;

namespace AdmissionAssistant.Web.Controllers
{
    [ApiKeyAuthorize]
    [RoutePrefix("api/ingest")]
    public class IngestController : ApiController
    {
        [HttpPost]
        [Route("")]
        public async Task<IHttpActionResult> UploadProspectus()
        {
            if (!Request.Content.IsMimeMultipartContent())
                return BadRequest("Expected multipart/form-data with a PDF file.");

            var provider = new MultipartMemoryStreamProvider();
            await Request.Content.ReadAsMultipartAsync(provider);
            var file = provider.Contents.FirstOrDefault();
            if (file == null)
                return BadRequest("No file uploaded.");

            var assistant = AdmissionAssistant.Web.Config.AssistantServiceFactory.Create(
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, AppSettings.VectorStorePath),
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, AppSettings.ProspectusStoragePath));

            var fileName = file.Headers.ContentDisposition?.FileName?.Trim('"') ?? "prospectus.pdf";

            using (var sourceStream = await file.ReadAsStreamAsync())
            {
                var result = await assistant.IngestAsync(sourceStream, fileName);
                return Ok(result);
            }
        }
    }
}
