#!/usr/bin/env python3
"""
Email Orchestrator MCP Server
Sends emails via SMTP with clean logging
"""

import asyncio
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from supabase import create_client, Client


class EmailOrchestrator:
    def __init__(self):
        # SMTP configuration
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USERNAME")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        
        # Supabase configuration
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        
        if not self.smtp_username or not self.smtp_password:
            raise ValueError("SMTP_USERNAME and SMTP_PASSWORD environment variables required")
            
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables required")
            
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)


    async def get_email_artifact(self, artifact_id: str) -> Dict:
        """Retrieve email artifact from Supabase"""
        try:
            response = self.supabase.table("email_artifacts").select("*").eq("id", artifact_id).execute()
            
            if not response.data:
                raise ValueError(f"Email artifact with ID {artifact_id} not found")
                
            return response.data[0]
            
        except Exception as e:
            raise ValueError(f"Failed to retrieve email artifact: {str(e)}")

    async def send_email(self, to: str, subject: str, html_content: str, context: str = "") -> Dict:
        """Send email via SMTP"""
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.smtp_username
            msg['To'] = to

            # Add HTML content
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)

            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)

            return {
                "success": True,
                "message": f"Email sent successfully",
                "to": to,
                "subject": subject,
                "context": context,
                "content_length": len(html_content)
            }

        except Exception as e:
            raise ValueError(f"Failed to send email: {str(e)}")



# Initialize the orchestrator
orchestrator = EmailOrchestrator()

# Create MCP server
app = Server("email-orchestrator")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """List available tools"""
    return [
        types.Tool(
            name="send_email_direct",
            description="Send an email directly with provided content",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Email address to send to"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line"
                    },
                    "html_content": {
                        "type": "string",
                        "description": "HTML content of the email"
                    },
                    "context": {
                        "type": "string",
                        "description": "Context description for logging (e.g., 'Newsletter Template to John Doe')",
                        "default": ""
                    }
                },
                "required": ["to", "subject", "html_content"]
            }
        ),
        types.Tool(
            name="send_email_from_artifact",
            description="Send an email using content from email_artifacts table in Supabase to one or multiple recipients",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "oneOf": [
                            {
                                "type": "string",
                                "description": "Single email address to send to"
                            },
                            {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Array of email addresses to send to"
                            }
                        ],
                        "description": "Email address(es) to send to - can be a single string or array of strings"
                    },
                    "artifact_id": {
                        "type": "string",
                        "description": "ID of the email artifact to retrieve from email_artifacts table"
                    }
                },
                "required": ["to", "artifact_id"]
            }
        )
    ]


@app.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    
    try:
        if name == "send_email_direct":
            to = arguments["to"]
            subject = arguments["subject"]
            html_content = arguments["html_content"]
            context = arguments.get("context", "Direct email")
            
            result = await orchestrator.send_email(to, subject, html_content, context)
            
            return [types.TextContent(
                type="text",
                text=f"✅ Email sent successfully!\n"
                     f"To: {result['to']}\n"
                     f"Subject: {result['subject']}\n"
                     f"Context: {result['context']}\n"
                     f"Content length: {result['content_length']} characters"
            )]

        elif name == "send_email_from_artifact":
            to = arguments["to"]
            artifact_id = arguments["artifact_id"]
            
            # Get email artifact from Supabase
            artifact = await orchestrator.get_email_artifact(artifact_id)
            
            # Extract email content from artifact
            subject = artifact.get("title", "")
            html_content = artifact.get("html_template", "")
            
            if not subject or not html_content:
                raise ValueError("Email artifact missing required fields: title or html_template")
            
            # Handle multiple recipients
            recipients = to if isinstance(to, list) else [to]
            results = []
            
            for recipient in recipients:
                result = await orchestrator.send_email(recipient, subject, html_content, f"Email from artifact {artifact_id}")
                results.append(result)
            
            # Format response for multiple recipients
            if len(recipients) == 1:
                result = results[0]
                return [types.TextContent(
                    type="text",
                    text=f"✅ Email sent from artifact!\n"
                         f"To: {result['to']}\n"
                         f"Subject: {result['subject']}\n"
                         f"Artifact ID: {artifact_id}\n"
                         f"Artifact Title: {artifact.get('title', 'Unknown')}\n"
                         f"Content length: {result['content_length']} characters"
                )]
            else:
                recipient_list = ", ".join([r['to'] for r in results])
                return [types.TextContent(
                    type="text",
                    text=f"✅ Email sent from artifact to {len(recipients)} recipients!\n"
                         f"To: {recipient_list}\n"
                         f"Subject: {results[0]['subject']}\n"
                         f"Artifact ID: {artifact_id}\n"
                         f"Artifact Title: {artifact.get('title', 'Unknown')}\n"
                         f"Content length: {results[0]['content_length']} characters"
                )]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"❌ Error: {str(e)}"
        )]


async def main():
    """Main entry point"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
