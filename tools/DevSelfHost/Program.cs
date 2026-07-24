using System;
using System.Threading;
using Microsoft.Owin.Hosting;

namespace DevSelfHost
{
    internal static class Program
    {
        private static void Main()
        {
            const string url = "http://localhost:5050/";
            using (WebApp.Start<Startup>(url))
            {
                Console.WriteLine("Admission Assistant running at " + url);
                Thread.Sleep(Timeout.Infinite);
            }
        }
    }
}
