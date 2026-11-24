using System.Reflection;

// A harmless PE fixture. It is never executed by the installer tests.
[assembly: AssemblyVersion("1.30.0.0")]
public static class ProductModuleFixture { public static int Value { get { return 1; } } }
