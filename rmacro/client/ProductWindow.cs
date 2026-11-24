using System;
using System.Reflection;
using System.Windows.Forms;
using RMFish;

namespace RMacro
{
    internal static class ProductUpdater
    {
        public static ProductSelection CheckAndInstall(string localDirectory)
        {
            return ProductUpdateStore.CheckAndInstall(localDirectory, new Version(ProductUpdateStore.EmbeddedVersion),
                LoaderUpdater.FindNewerProduct, LoaderUpdater.DownloadVerified, ProductWindow.ValidateModule);
        }
    }

    // The product can be the embedded baseline or a separately verified DLL.
    // Both use exactly the same lease/stop/drain lifecycle. The reflection
    // contract intentionally uses only framework types, so future product
    // builds do not need a new loader or a copy of its assembly.
    internal sealed class ProductWindow
    {
        public readonly Form Form;
        private readonly Action<string> revoke;
        private readonly Func<bool> finish;

        private ProductWindow(Form form, Action<string> revoke, Func<bool> finish)
        { Form = form; this.revoke = revoke; this.finish = finish; }

        private static MethodInfo Method(Type type, string name, Type returnType, Type[] parameters)
        {
            MethodInfo method = type.GetMethod(name, BindingFlags.Public | BindingFlags.Static, null, parameters, null);
            if (method == null || method.ReturnType != returnType)
                throw new InvalidOperationException("Обновление RMFish несовместимо с этой версией лоадера.");
            return method;
        }

        private static Type ValidateEntry(Assembly assembly, Version version)
        {
            AssemblyName identity = assembly.GetName();
            if (version == null || identity.Name != "RMFishProduct" ||
                identity.Version != new Version(version.Major, version.Minor, version.Build, 0))
                throw new InvalidOperationException("Версия модуля RMFish не соответствует проверенному обновлению.");
            Type entry = assembly.GetType("RMFish.ProductEntry", true, false);
            FieldInfo protocol = entry.GetField("ContractVersion", BindingFlags.Public | BindingFlags.Static);
            if (protocol == null || !protocol.IsLiteral || protocol.FieldType != typeof(int) ||
                (int)protocol.GetRawConstantValue() != 1)
                throw new InvalidOperationException("Неизвестный формат модуля RMFish.");
            Method(entry, "Create", typeof(Form), new Type[] { typeof(string), typeof(string), typeof(Func<bool>) });
            Method(entry, "Revoke", typeof(void), new Type[] { typeof(Form), typeof(string) });
            Method(entry, "Finish", typeof(bool), new Type[] { typeof(Form) });
            return entry;
        }

        // Inspect the contract before committing the new installed pointer.
        // Loading metadata does not invoke the product's Create method.
        public static Assembly ValidateModule(byte[] bytes, Version version)
        {
            Assembly assembly = Assembly.Load(bytes);
            ValidateEntry(assembly, version);
            return assembly;
        }

        public static ProductWindow Create(ProductSelection selection, string directory, string settingsRoot, Func<bool> authorized)
        {
            if (selection == null || authorized == null) throw new ArgumentNullException("selection");
            if (selection.AssemblyBytes == null)
            {
                MainForm builtIn = new MainForm(directory, settingsRoot, authorized);
                return new ProductWindow(builtIn, builtIn.RevokeAuthorization, builtIn.FinishWorkerShutdown);
            }
            Assembly assembly = selection.ValidatedAssembly ?? ValidateModule(selection.AssemblyBytes, selection.Version);
            Type entry = ValidateEntry(assembly, selection.Version);
            MethodInfo create = Method(entry, "Create", typeof(Form), new Type[] { typeof(string), typeof(string), typeof(Func<bool>) });
            MethodInfo revokeMethod = Method(entry, "Revoke", typeof(void), new Type[] { typeof(Form), typeof(string) });
            MethodInfo finishMethod = Method(entry, "Finish", typeof(bool), new Type[] { typeof(Form) });
            Form form = create.Invoke(null, new object[] { directory, settingsRoot, authorized }) as Form;
            if (form == null || form.IsDisposed || form.Visible)
            {
                if (form != null) form.Dispose();
                throw new InvalidOperationException("Модуль RMFish не создал корректное окно.");
            }
            return new ProductWindow(form,
                delegate(string reason) { revokeMethod.Invoke(null, new object[] { form, reason }); },
                delegate { return (bool)finishMethod.Invoke(null, new object[] { form }); });
        }

        // Called by the lease thread; product contract requires a direct,
        // thread-safe stop request, not merely a queued WinForms message.
        public void Revoke(string reason) { revoke(reason); }

        // If a module fails its shutdown check, keep the mutex rather than
        // allowing another product instance while an input worker might live.
        public bool Finish()
        {
            try { return finish(); }
            catch (Exception) { return false; }
        }
    }
}
