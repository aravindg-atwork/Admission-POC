using System.IO;
using System.Threading.Tasks;

namespace AdmissionAssistant.Core.Rag
{
    // Same contract whether the pipeline runs in-process (LocalAssistantService)
    // or is delegated to an external microservice (RemoteAssistantService) —
    // callers (the Web API controllers) don't need to know which.
    public interface IAssistantService
    {
        Task<RagAnswer> AskAsync(string question);
        Task<IngestResult> IngestAsync(Stream pdfStream, string fileName);
    }
}
