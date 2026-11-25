using System;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("RMFish Product")]
[assembly: AssemblyDescription("RMFish product module for Eternal Core")]
[assembly: AssemblyProduct("RMFish")]
[assembly: AssemblyVersion("1.30.0.0")]
[assembly: AssemblyFileVersion("1.30.0.0")]
[assembly: AssemblyInformationalVersion("1.30.0")]

namespace RMFish
{
    // Stable loader/module contract. The loader supplies and owns the lease,
    // runtime paths and single-instance mutex. Do not start a worker unless
    // the authorization delegate returns true; revocation must stop it even
    // while the UI is blocked, and Finish must wait for all input workers.
    public static class ProductEntry
    {
        public const int ContractVersion = 1;

        public static Form Create(string directory, string settingsRoot, Func<bool> authorized)
        {
            if (authorized == null) throw new ArgumentNullException("authorized");
            return new MainForm(directory, settingsRoot, authorized);
        }

        public static void Revoke(Form form, string reason)
        {
            MainForm product = form as MainForm;
            if (product == null) throw new ArgumentException("Unexpected RMFish window.");
            product.RevokeAuthorization(reason);
        }

        public static bool Finish(Form form)
        {
            MainForm product = form as MainForm;
            if (product == null) return false;
            return product.FinishWorkerShutdown();
        }
    }
}
