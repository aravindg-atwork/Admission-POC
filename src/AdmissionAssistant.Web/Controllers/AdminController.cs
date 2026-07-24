using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Web.Http;
using AdmissionAssistant.Core.Config;
using AdmissionAssistant.Core.Security;

namespace AdmissionAssistant.Web.Controllers
{
    // Key management is intentionally separate from api/chat's ApiKeyAuthorize gate:
    // this manages keys, so it's protected by its own admin token instead.
    [RoutePrefix("admin/keys")]
    public class AdminController : ApiController
    {
        [HttpGet]
        [Route("")]
        public IHttpActionResult List()
        {
            var authError = CheckAdmin();
            if (authError != null) return authError;

            return Ok(GetStore().List());
        }

        [HttpPost]
        [Route("")]
        public IHttpActionResult Create([FromBody] CreateKeyRequest request)
        {
            var authError = CheckAdmin();
            if (authError != null) return authError;

            return Ok(GetStore().Create(request?.Label));
        }

        [HttpPatch]
        [Route("{id}")]
        public IHttpActionResult SetActive(string id, [FromBody] SetActiveRequest request)
        {
            var authError = CheckAdmin();
            if (authError != null) return authError;

            var entry = GetStore().SetActive(id, request?.Active ?? false);
            return entry == null ? (IHttpActionResult)NotFound() : Ok(entry);
        }

        [HttpDelete]
        [Route("{id}")]
        public IHttpActionResult Delete(string id)
        {
            var authError = CheckAdmin();
            if (authError != null) return authError;

            return GetStore().Delete(id) ? (IHttpActionResult)Ok() : NotFound();
        }

        private IHttpActionResult CheckAdmin()
        {
            var headerValues = Request.Headers
                .FirstOrDefault(h => string.Equals(h.Key, "X-Admin-Token", StringComparison.OrdinalIgnoreCase))
                .Value;

            var provided = headerValues?.FirstOrDefault();
            var expected = AppSettings.AdminToken;

            if (string.IsNullOrEmpty(expected) || provided != expected)
            {
                return ResponseMessage(Request.CreateErrorResponse(HttpStatusCode.Unauthorized, "Invalid admin token."));
            }

            return null;
        }

        private static ApiKeyStore GetStore()
        {
            var keysPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, AppSettings.ApiKeysPath);
            return new ApiKeyStore(keysPath);
        }
    }

    public class CreateKeyRequest
    {
        public string Label { get; set; }
    }

    public class SetActiveRequest
    {
        public bool Active { get; set; }
    }
}
