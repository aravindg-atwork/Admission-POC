using System;
using System.IO;
using System.Web.Http;
using AdmissionAssistant.Web;
using Microsoft.Owin.FileSystems;
using Microsoft.Owin.StaticFiles;
using Owin;

namespace DevSelfHost
{
    public class Startup
    {
        public void Configuration(IAppBuilder app)
        {
            var webRoot = Environment.GetEnvironmentVariable("WEB_ROOT")
                ?? Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "..", "..", "..", "..", "src", "AdmissionAssistant.Web"));

            app.Use<AspxShellMiddleware>(webRoot);

            var config = new HttpConfiguration();
            WebApiConfig.Register(config);
            app.UseWebApi(config);

            app.UseFileServer(new FileServerOptions
            {
                FileSystem = new PhysicalFileSystem(webRoot),
                EnableDefaultFiles = false,
                StaticFileOptions = { ServeUnknownFileTypes = true }
            });
        }
    }
}
