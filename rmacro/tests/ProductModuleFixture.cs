using System.Reflection;

// A harmless PE fixture. It is never executed by the installer tests.
#if NEWER_FIXTURE
[assembly: AssemblyVersion("1.31.0.0")]
#else
[assembly: AssemblyVersion("1.30.0.0")]
#endif
public static class ProductModuleFixture { public static int Value { get { return 1; } } }
