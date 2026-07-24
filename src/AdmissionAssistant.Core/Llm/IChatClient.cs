using System.Threading.Tasks;

namespace AdmissionAssistant.Core.Llm
{
    public interface IChatClient
    {
        Task<string> AskAsync(string systemPrompt, string userPrompt);
    }
}
