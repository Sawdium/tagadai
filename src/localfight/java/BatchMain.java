import java.io.BufferedReader;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;

import com.leekwars.generator.Generator;
import com.leekwars.generator.Log;
import com.leekwars.generator.outcome.Outcome;
import com.leekwars.generator.scenario.Scenario;
import com.leekwars.generator.test.LocalDbRegisterManager;
import com.leekwars.generator.test.LocalTrophyManager;

import leekscript.compiler.LeekScript;
import leekscript.compiler.resolver.NativeFileSystem;

/**
 * Persistent generator worker: one JVM, many fights.
 *
 * The stock entry point (com.leekwars.Main) runs one scenario per JVM, so
 * every fight pays JVM start-up and, worse, a full JIT warm-up of the
 * compiled AI -- which is where most of a fight's CPU goes, and why parallel
 * one-shot JVMs contend instead of scaling. This class does exactly what
 * Main does, in a loop: read a scenario path per line on stdin, print the
 * outcome JSON on one line to stdout. The compiled AI stays in the RAM cache
 * and the JIT'd code stays hot.
 *
 * Only outcomes go to the real stdout; everything the generator prints is
 * redirected to stderr so a stray log line can never desynchronise the
 * protocol. A fight that throws is reported as {"error": "..."} on its own
 * line, so the caller always gets exactly one line per scenario.
 *
 * Built by src/localfight/batch.py against generator.jar; run with the
 * generator directory as the working directory, like Main.
 */
public class BatchMain {

	public static void main(String[] args) throws IOException {
		PrintStream results = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
		System.setOut(System.err);

		boolean nocache = false;
		for (String arg : args) {
			if (arg.equals("--nocache")) nocache = true;
		}
		Log.enable(false);
		LeekScript.setFileSystem(new NativeFileSystem());
		Generator generator = new Generator();
		generator.setCache(!nocache);
		results.println("READY");

		BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
		String line;
		while ((line = in.readLine()) != null) {
			line = line.trim();
			if (line.isEmpty()) continue;
			String out;
			try {
				Scenario scenario = Scenario.fromFile(new File(line));
				if (scenario == null) {
					out = "{\"error\":\"Failed to parse scenario\"}";
				} else {
					Outcome outcome = generator.runScenario(scenario, null, new LocalDbRegisterManager(), new LocalTrophyManager());
					out = outcome.toJson().toString();
				}
			} catch (Throwable t) {
				StringWriter sw = new StringWriter();
				t.printStackTrace(new PrintWriter(sw));
				out = "{\"error\":" + quote(sw.toString()) + "}";
			}
			results.println(out);
		}
	}

	/** JSON string literal, escaping quotes, backslashes and control characters. */
	static String quote(String s) {
		StringBuilder sb = new StringBuilder(s.length() + 16).append('"');
		for (int i = 0; i < s.length(); i++) {
			char c = s.charAt(i);
			switch (c) {
				case '"': sb.append("\\\""); break;
				case '\\': sb.append("\\\\"); break;
				case '\n': sb.append("\\n"); break;
				case '\r': sb.append("\\r"); break;
				case '\t': sb.append("\\t"); break;
				default:
					if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
					else sb.append(c);
			}
		}
		return sb.append('"').toString();
	}
}
