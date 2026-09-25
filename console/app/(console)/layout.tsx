import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <Topbar />
        <main className="flex-1 px-5 md:px-8 pb-12">{children}</main>
      </div>
    </div>
  );
}
