import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import { connection } from "next/server"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { DemoProvider } from "@/lib/demo"
import "./globals.css"

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] })
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] })

export const metadata: Metadata = {
  title: { default: "Amber", template: "%s · Amber" },
  description: "Ask questions across your company's documents and Google Drive.",
}

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // The CSP nonce is per request, so every page must render dynamically.
  await connection()

  return (
    <html lang="en" className={`dark ${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="amber-backdrop flex min-h-full flex-col">
        <DemoProvider>
          <TooltipProvider>{children}</TooltipProvider>
        </DemoProvider>
        <Toaster theme="dark" position="bottom-right" />
      </body>
    </html>
  )
}
