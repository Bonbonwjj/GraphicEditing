$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
class NativeFolderOpenDialog {}
[ComImport, Guid("42F85136-DB7E-439C-85F1-E4075D135FC8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface INativeFolderDialog {
 [PreserveSig] int Show(IntPtr owner);
 void SetFileTypes(uint count, IntPtr types);
 void SetFileTypeIndex(uint index);
 void GetFileTypeIndex(out uint index);
 void Advise(IntPtr events, out uint cookie);
 void Unadvise(uint cookie);
 void SetOptions(uint options);
 void GetOptions(out uint options);
 void SetDefaultFolder(IntPtr folder);
 void SetFolder(IntPtr folder);
 void GetFolder(out IntPtr folder);
 void GetCurrentSelection(out IntPtr item);
 void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
 void GetFileName(out IntPtr name);
 void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
 void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
 void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
 void GetResult(out INativeFolderItem item);
 void AddPlace(IntPtr item, uint location);
 void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
 void Close(int result);
 void SetClientGuid(ref Guid guid);
 void ClearClientData();
 void SetFilter(IntPtr filter);
}
[ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface INativeFolderItem {
 void BindToHandler(IntPtr context, ref Guid handler, ref Guid iid, out IntPtr result);
 void GetParent(out INativeFolderItem parent);
 void GetDisplayName(uint format, out IntPtr name);
 void GetAttributes(uint mask, out uint attributes);
 void Compare(INativeFolderItem other, uint hint, out int order);
}
public static class NativeFolderPicker {
 public static string Choose(IntPtr owner) {
  INativeFolderDialog dialog = (INativeFolderDialog)new NativeFolderOpenDialog();
  INativeFolderItem item = null;
  try {
   uint options; dialog.GetOptions(out options);
   dialog.SetOptions(options | 0x20u | 0x40u | 0x800u | 0x8u | 0x2000000u);
   dialog.SetTitle("选择要导入并拆分的工程文件夹");
   dialog.SetOkButtonLabel("选择此文件夹");
   int result = dialog.Show(owner);
   if (result == unchecked((int)0x800704C7)) return "";
   if (result < 0) Marshal.ThrowExceptionForHR(result);
   dialog.GetResult(out item);
   IntPtr path; item.GetDisplayName(0x80058000u, out path);
   try { return Marshal.PtrToStringUni(path); }
   finally { Marshal.FreeCoTaskMem(path); }
  } finally {
   if (item != null) Marshal.ReleaseComObject(item);
   Marshal.ReleaseComObject(dialog);
  }
 }
}
'@
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.StartPosition = 'CenterScreen'
$owner.Width = 1; $owner.Height = 1
try {
  $owner.Show(); $owner.Activate()
  [Console]::WriteLine([NativeFolderPicker]::Choose($owner.Handle))
} finally { $owner.Close(); $owner.Dispose() }
