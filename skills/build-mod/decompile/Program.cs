using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.Metadata;
using ICSharpCode.Decompiler.TypeSystem;

if (args.Length < 2)
{
    Console.Error.WriteLine("Usage: decompile ASSEMBLY TYPE [REFERENCE_DIRECTORY ...]");
    return 2;
}

try
{
    string assemblyPath = Path.GetFullPath(args[0]);
    if (!File.Exists(assemblyPath)) throw new FileNotFoundException("Assembly not found", assemblyPath);
    var resolver = new UniversalAssemblyResolver(assemblyPath, true, ".NETFramework,Version=v4.7.2");
    foreach (string directory in args.Skip(2))
    {
        string path = Path.GetFullPath(directory);
        if (!Directory.Exists(path)) throw new DirectoryNotFoundException("Reference directory not found: " + path);
        resolver.AddSearchDirectory(path);
    }
    var decompiler = new CSharpDecompiler(assemblyPath, resolver, new DecompilerSettings());
    Console.WriteLine(decompiler.DecompileTypeAsString(new FullTypeName(args[1])));
    return 0;
}
catch (Exception ex)
{
    Console.Error.WriteLine(ex.GetType().Name + ": " + ex.Message);
    Console.Error.WriteLine("Check the fully qualified type and supply installed game/mod reference directories.");
    return 1;
}
