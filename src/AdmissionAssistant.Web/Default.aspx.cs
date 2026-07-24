using System;
using System.IO;
using AdmissionAssistant.Core.Config;
using AdmissionAssistant.Core.Security;

namespace AdmissionAssistant.Web
{
    public partial class Default : System.Web.UI.Page
    {
        // The admission site's own chat widget authenticates with an always-on,
        // auto-provisioned first-party key, injected here so the browser never needs
        // it hard-coded and it can't be confused with keys issued to other consumers.
        protected string DefaultApiKey;

        protected void Page_Load(object sender, EventArgs e)
        {
            var keysPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, AppSettings.ApiKeysPath);
            var store = new ApiKeyStore(keysPath);
            DefaultApiKey = store.GetOrCreateDefault(AppSettings.DefaultApiKeyLabel).Key;
        }
    }
}
