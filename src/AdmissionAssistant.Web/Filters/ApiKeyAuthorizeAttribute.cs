using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Web.Http.Controllers;
using System.Web.Http.Filters;
using AdmissionAssistant.Core.Config;
using AdmissionAssistant.Core.Security;

namespace AdmissionAssistant.Web.Filters
{
    // Gates an ApiController action behind a valid, active key from ApiKeyStore.
    // Every consumer (the admission site's own widget, the browser extension,
    // any other integration) presents its own X-API-Key, so any one can be
    // revoked from the admin panel without touching the others.
    public class ApiKeyAuthorizeAttribute : AuthorizationFilterAttribute
    {
        public override void OnAuthorization(HttpActionContext actionContext)
        {
            var keysPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, AppSettings.ApiKeysPath);
            var store = new ApiKeyStore(keysPath);

            var headerValues = actionContext.Request.Headers
                .FirstOrDefault(h => string.Equals(h.Key, "X-API-Key", StringComparison.OrdinalIgnoreCase))
                .Value;

            var providedKey = headerValues?.FirstOrDefault();

            if (!store.IsActive(providedKey))
            {
                actionContext.Response = actionContext.Request.CreateErrorResponse(
                    HttpStatusCode.Unauthorized, "Missing or inactive API key.");
            }
        }
    }
}
