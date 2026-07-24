using System;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Owin;

namespace DevSelfHost
{
    // Serves the real Default.aspx unmodified except for stripping the leading
    // <%@ Page %> directive, which only means something inside IIS/ASP.NET and has
    // no visual content - a raw browser request outside that pipeline can't execute it.
    public class AspxShellMiddleware : OwinMiddleware
    {
        private readonly string _webRoot;

        public AspxShellMiddleware(OwinMiddleware next, string webRoot) : base(next)
        {
            _webRoot = webRoot;
        }

        public override async Task Invoke(IOwinContext context)
        {
            var path = context.Request.Path.Value;
            if (path == "/" || string.Equals(path, "/Default.aspx", StringComparison.OrdinalIgnoreCase))
            {
                var raw = File.ReadAllText(Path.Combine(_webRoot, "Default.aspx"));
                var html = Regex.Replace(raw, @"^<%@.*?%>\s*", "", RegexOptions.Singleline);
                context.Response.ContentType = "text/html";
                await context.Response.WriteAsync(html);
                return;
            }

            await Next.Invoke(context);
        }
    }
}
