<%@ WebHandler Language="C#" Class="MafsuMitraProxy" %>

using System;
using System.IO;
using System.Net;
using System.Text;
using System.Web;

public sealed class MafsuMitraProxy : IHttpHandler
{
    private const string UpstreamBase = "http://159.69.210.30";
    private const int MaxRequestBytes = 16384;

    public bool IsReusable { get { return true; } }

    public void ProcessRequest(HttpContext context)
    {
        context.Response.Cache.SetCacheability(HttpCacheability.NoCache);
        context.Response.Cache.SetNoStore();
        context.Response.TrySkipIisCustomErrors = true;

        string endpoint = (context.Request.QueryString["endpoint"] ?? "").ToLowerInvariant();
        bool isHealth = endpoint == "healthz";
        bool isChat = endpoint == "chat";

        if ((!isHealth && !isChat) ||
            (isHealth && context.Request.HttpMethod != "GET") ||
            (isChat && context.Request.HttpMethod != "POST"))
        {
            WriteError(context, 405, "Unsupported MITRA proxy request.");
            return;
        }

        if (isChat && (context.Request.ContentLength < 0 ||
                       context.Request.ContentLength > MaxRequestBytes))
        {
            WriteError(context, 413, "Request is too large.");
            return;
        }

        try
        {
            string target = UpstreamBase + "/api/" + endpoint;
            HttpWebRequest upstream = (HttpWebRequest)WebRequest.Create(target);
            upstream.Method = context.Request.HttpMethod;
            upstream.Timeout = 120000;
            upstream.ReadWriteTimeout = 120000;
            upstream.AllowAutoRedirect = false;
            upstream.ContentType = "application/json; charset=utf-8";
            upstream.Accept = "application/json";
            upstream.Headers["X-Real-IP"] = context.Request.UserHostAddress ?? "";
            upstream.Headers["X-Forwarded-Proto"] = "https";

            if (isChat)
            {
                upstream.ContentLength = context.Request.ContentLength;
                using (Stream destination = upstream.GetRequestStream())
                {
                    CopyLimited(context.Request.InputStream, destination, MaxRequestBytes);
                }
            }

            using (HttpWebResponse response = (HttpWebResponse)upstream.GetResponse())
            {
                Relay(context, response);
            }
        }
        catch (WebException ex)
        {
            HttpWebResponse response = ex.Response as HttpWebResponse;
            if (response != null)
            {
                using (response) { Relay(context, response); }
                return;
            }
            WriteError(context, 502, "MAFSU MITRA is temporarily unreachable.");
        }
        catch
        {
            WriteError(context, 502, "MAFSU MITRA is temporarily unreachable.");
        }
    }

    private static void Relay(HttpContext context, HttpWebResponse upstream)
    {
        context.Response.StatusCode = (int)upstream.StatusCode;
        context.Response.ContentType = "application/json; charset=utf-8";
        using (Stream source = upstream.GetResponseStream())
        {
            if (source != null) { source.CopyTo(context.Response.OutputStream); }
        }
    }

    private static void CopyLimited(Stream source, Stream destination, int limit)
    {
        byte[] buffer = new byte[4096];
        int total = 0;
        int read;
        while ((read = source.Read(buffer, 0, buffer.Length)) > 0)
        {
            total += read;
            if (total > limit) { throw new InvalidOperationException("Request too large"); }
            destination.Write(buffer, 0, read);
        }
    }

    private static void WriteError(HttpContext context, int status, string message)
    {
        context.Response.StatusCode = status;
        context.Response.ContentType = "application/json; charset=utf-8";
        string safe = message.Replace("\\", "\\\\").Replace("\"", "\\\"");
        context.Response.Write("{\"detail\":\"" + safe + "\"}");
    }
}
