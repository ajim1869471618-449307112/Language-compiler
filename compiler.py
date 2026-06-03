import os
import uuid
import shutil
import subprocess
import hashlib
import random
import traceback
import json
import threading
import re
import signal
import zipfile
import stat
import binascii

try:
    import llvmlite.ir as ir
    import llvmlite.binding as llvm
except ImportError:
    pass

translation_lock = threading.Lock()

class TokenType:
    KEYWORD = "KEYWORD"
    IDENTIFIER = "IDENTIFIER"
    SYMBOL = "SYMBOL"
    STRING = "STRING"

class Token:
    def __init__(self, type_, value):
        self.type = type_
        self.value = value

class Lexer:
    def __init__(self, text, db_rules):
        self.text = text
        self.pos = 0
        self.db_rules = db_rules
        self.flat_rules = {}
        for k, v in db_rules.items():
            self.flat_rules[k] = v[0] if isinstance(v, list) else v

    def tokenize(self):
        tokens = []
        text_length = len(self.text)
        while self.pos < text_length:
            char = self.text[self.pos]
            if char.isspace():
                self.pos += 1
                continue
            if char.isalnum() or char == '_':
                start = self.pos
                while self.pos < text_length and (self.text[self.pos].isalnum() or self.text[self.pos] == '_'):
                    self.pos += 1
                word = self.text[start:self.pos]
                if word in self.flat_rules:
                    tokens.append(Token(TokenType.KEYWORD, self.flat_rules[word]))
                else:
                    tokens.append(Token(TokenType.IDENTIFIER, word))
            else:
                tokens.append(Token(TokenType.SYMBOL, char))
                self.pos += 1
        return tokens

class ASTNode:
    def __init__(self, type_, value=None, children=None):
        self.type = type_
        self.value = value
        self.children = children or []

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def parse(self):
        root = ASTNode("PROGRAM")
        while self.pos < len(self.tokens):
            tok = self.tokens[self.pos]
            root.children.append(ASTNode("STATEMENT", value=tok.value))
            self.pos += 1
        return root

def generate_smali_from_ast(ast, out_dir, file_index=0):
    os.makedirs(out_dir, exist_ok=True)
    smali_path = os.path.join(out_dir, f"CoreLogic_{file_index}.smali")
    
    methods_code = ""
    register_count = 2

    for node in ast.children:
        if node.type == "STATEMENT":
            if node.value == "PRINT_LOG":
                methods_code += """
    sget-object v0, Ljava/lang/System;->out:Ljava/io/PrintStream;
    const-string v1, "SMD_CORE_EXECUTION"
    invoke-virtual {v0, v1}, Ljava/io/PrintStream;->println(Ljava/lang/String;)V
"""
            elif node.value in ["EXIT", "SYSTEM_EXIT"]:
                methods_code += """
    const/4 v0, 0x0
    invoke-static {v0}, Ljava/lang/System;->exit(I)V
"""
            elif node.value == "MATH_ADD":
                if register_count < 4:
                    register_count = 4
                methods_code += """
    const/4 v0, 0x5
    const/4 v1, 0xa
    add-int v2, v0, v1
"""

    smali_code = f""".class public Lcom/azim/app/CoreLogic{file_index};
.super Ljava/lang/Object;
.method public constructor <init>()V
    .registers 1
    invoke-direct {{p0}}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static main([Ljava/lang/String;)V
    .registers {register_count}
{methods_code}
    return-void
.end method
"""
    with open(smali_path, "w", encoding="utf-8") as f:
        f.write(smali_code)
    return smali_path

def init_llvm_environment():
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    module = ir.Module(name="smd_core_module")
    func_type = ir.FunctionType(ir.IntType(32), [])
    func = ir.Function(module, func_type, name="main")
    block = func.append_basic_block(name="entry")
    builder = ir.IRBuilder(block)
    return module, builder

def inject_ast_to_llvm(ast, builder, module):
    for node in ast.children:
        if node.type == "STATEMENT":
            if node.value == "PRINT_LOG":
                voidptr_ty = ir.IntType(8).as_pointer()
                printf_ty = ir.FunctionType(ir.IntType(32), [voidptr_ty], var_arg=True)
                try:
                    printf = module.get_global("printf")
                except KeyError:
                    printf = ir.Function(module, printf_ty, name="printf")
                
                fmt = "SMD_CORE_EXECUTION\n\0"
                c_fmt = ir.Constant(ir.ArrayType(ir.IntType(8), len(fmt)), bytearray(fmt.encode("utf8")))
                global_fmt = ir.GlobalVariable(module, c_fmt.type, name=f"fstr_{uuid.uuid4().hex[:8]}")
                global_fmt.linkage = 'internal'
                global_fmt.global_constant = True
                global_fmt.initializer = c_fmt
                
                fmt_ptr = builder.bitcast(global_fmt, voidptr_ty)
                builder.call(printf, [fmt_ptr])

            elif node.value in ["EXIT", "SYSTEM_EXIT"]:
                exit_func_type = ir.FunctionType(ir.VoidType(), [ir.IntType(32)])
                try:
                    exit_func = module.get_global("exit")
                except KeyError:
                    exit_func = ir.Function(module, exit_func_type, name="exit")
                builder.call(exit_func, [ir.Constant(ir.IntType(32), 0)])
            
            elif node.value == "MATH_ADD":
                a = ir.Constant(ir.IntType(32), 5)
                b = ir.Constant(ir.IntType(32), 10)
                builder.add(a, b, name="smd_add_tmp")

def finalize_llvm_module(module, builder):
    if not builder.block.is_terminated:
        builder.ret(ir.Constant(ir.IntType(32), 0))
    return str(module)class TrieNode:
    def __init__(self):
        self.children = {}
        self.output = None

class AhoCorasick:
    def __init__(self):
        self.root = TrieNode()

    def add_word(self, word, output):
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.output = (word, output)

    def is_boundary(self, char):
        return not char.isalnum() and char != '_'

    def replace(self, text):
        result = []
        i = 0
        n = len(text)
        while i < n:
            node = self.root
            match_len = 0
            best_match = None
            j = i
            while j < n and text[j] in node.children:
                node = node.children[text[j]]
                if node.output is not None:
                    match_len = j - i + 1
                    _, best_match = node.output
                j += 1
                
            if best_match is not None:
                left_bound = (i == 0) or self.is_boundary(text[i-1])
                right_bound = (i + match_len == n) or self.is_boundary(text[i + match_len])
                if left_bound and right_bound:
                    result.append(best_match)
                    i += match_len
                    continue
                    
            result.append(text[i])
            i += 1
        return "".join(result)

def build_trie(db_rules):
    trie = AhoCorasick()
    for key, values in db_rules.items():
        if values and isinstance(values, list):
            trie.add_word(key, str(values[0]))
        elif isinstance(values, str):
            trie.add_word(key, values)
    return trie

def sanitize_filename(filename):
    return os.path.basename(filename)

def sanitize_traceback(tb_str, base_dir):
    clean_tb = tb_str.replace(base_dir, "[SERVER_WORKSPACE]")
    clean_tb = re.sub(r'File ".*[/\\](compiler\.py|main\.py)"', r'File "[\1]"', clean_tb)
    return clean_tb

def safe_run(cmd, cwd=None, env=None, timeout=60):
    process = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
    try:
        out, err = process.communicate(timeout=timeout)
        if process.returncode != 0:
            raise Exception(err.decode('utf-8'))
        return out.decode('utf-8')
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        raise Exception(f"Process Timeout: Zombie killed for cmd {cmd[0]}")
    except Exception as e:
        os.killpg(process.pid, signal.SIGKILL)
        raise e

def apply_source_masking(content, ext):
    if ext in ['.xml', '.bn', '.ajim']:
        return content + "\n"
    elif ext in ['.azim']:
        return content + "\n// ছায়া ঘনালে আসল কোড হারিয়ে যায়... "
    return content

def generate_honey_pots(target_dir):
    dummy_names = ['শালা.শালী', 'প্রেমিক.প্রেমিকা', 'আমি.তুমি', 'আমার.তোমার', 'গার্লফ্রেন্ড.বয়ফ্রেন্ড']
    emojis = ['😀', '🤖', '🔥', '💀', '👻', '👽', '💻', '😈']
    os.makedirs(target_dir, exist_ok=True)
    num_files = random.randint(100, 150)
    for i in range(num_files):
        name = f"{random.choice(dummy_names)}_{i}.sys"
        file_path = os.path.join(target_dir, name)
        size = random.randint(2048, 5120)
        junk_data = os.urandom(size - 100)
        emoji_str = "".join(random.choices(emojis, k=15)).encode('utf-8')
        with open(file_path, "wb") as f:
            f.write(junk_data + emoji_str)

def generate_unique_keystore(user_id, alias="androiddebugkey"):
    keystores_dir = os.path.join(os.getcwd(), "keystores")
    os.makedirs(keystores_dir, exist_ok=True)
    keystore_path = os.path.join(keystores_dir, f"keystore_{user_id}.jks")
    if not os.path.exists(keystore_path):
        safe_run([
            "keytool", "-genkey", "-v", "-keystore", keystore_path,
            "-alias", alias, "-storepass", "android",
            "-keypass", "android", "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "10000", "-dname", "CN=Android Debug,O=Android,C=US"
        ], timeout=20)
    return keystore_path

def extract_permissions_from_cood(cood_content, db_rules):
    perms_to_inject = []
    for word, mapped_val in db_rules.items():
        val = str(mapped_val[0]) if isinstance(mapped_val, list) else str(mapped_val)
        if "android.permission." in val and word in cood_content:
            perms_to_inject.append(f'<uses-permission android:name="{val}"/>')
    return "\n    ".join(set(perms_to_inject))

def inject_firebase_config(json_content, values_dir):
    try:
        data = json.loads(json_content)
        project_id = data.get("project_info", {}).get("project_id", "")
        api_key = data.get("client", [{}])[0].get("api_key", [{}])[0].get("current_key", "")
        app_id = data.get("client", [{}])[0].get("client_info", {}).get("mobilesdk_app_id", "")
        
        xml_content = f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="google_app_id">{app_id}</string>
    <string name="google_api_key">{api_key}</string>
    <string name="project_id">{project_id}</string>
</resources>"""
        
        os.makedirs(values_dir, exist_ok=True)
        with open(os.path.join(values_dir, "firebase_strings.xml"), "w", encoding="utf-8") as f:
            f.write(xml_content)
    except:
        pass

def get_android_tools():
    android_home = os.environ.get("ANDROID_HOME", "/opt/android")
    build_tools_dir = os.path.join(android_home, "build-tools")
    platforms_dir = os.path.join(android_home, "platforms")

    aapt2_path = "aapt2"
    android_jar = "android.jar"

    if os.path.exists(build_tools_dir):
        versions = sorted(os.listdir(build_tools_dir), reverse=True)
        if versions:
            latest = versions[0]
            aapt2_path = os.path.join(build_tools_dir, latest, "aapt2")

    if os.path.exists(platforms_dir):
        platforms = sorted([p for p in os.listdir(platforms_dir) if p.startswith("android-")], reverse=True)
        if platforms:
            android_jar = os.path.join(platforms_dir, platforms[0], "android.jar")

    return aapt2_path, android_jar

def get_ios_sdk():
    try:
        return subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]).decode().strip()
    except Exception:
        return ""

def process_and_build(files_data, db_rules, test_mode=False, user_id="default_user"):
    trie = build_trie(db_rules)
    
    if test_mode:
        test_output = ""
        for filename, content in files_data.items():
            safe_name = sanitize_filename(filename)
            if safe_name == 'cood.txt':
                perms = extract_permissions_from_cood(content, db_rules)
                test_output += f"--- {safe_name} (Permissions) ---\n{perms}\n\n"
                continue
            
            lexer = Lexer(content, db_rules)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            ast = parser.parse()
            test_output += f"--- {safe_name} (AST Generated) ---\n[AST Nodes: {len(ast.children)}]\n\n"
        return test_output

    if 'all.am' not in files_data:
        raise Exception("Fatal Error: all.am configuration file is strictly required.")
        
    router_config = files_data['all.am'].strip().splitlines()
    if len(router_config) < 2:
        raise Exception("Fatal Error: all.am must specify Target OS (Line 1) and Build Type (Line 2).")
        
    target_os = router_config[0].strip().lower()
    build_type = router_config[1].strip().lower()
    
    build_id = str(uuid.uuid4())
    base_dir = os.path.join(os.getcwd(), "builds", build_id)
    
    src_dir = os.path.join(base_dir, "src")
    res_dir = os.path.join(base_dir, "res")
    layout_dir = os.path.join(res_dir, "layout")
    values_dir = os.path.join(res_dir, "values")
    assets_dir = os.path.join(base_dir, "assets")
    smali_dir = os.path.join(base_dir, "smali")
    
    os.makedirs(layout_dir, exist_ok=True)
    os.makedirs(values_dir, exist_ok=True)
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(smali_dir, exist_ok=True)
    os.makedirs("downloads", exist_ok=True)
    
    core_hashes = {}
    manifest_path = os.path.join(base_dir, "AndroidManifest.xml")
    
    shared_state = {
        "manifest_content": "",
        "permissions_xml": "",
        "ast_forest": []
    }
    
    try:
        def process_file(filename, content):
            safe_name = sanitize_filename(filename)
            ext = os.path.splitext(safe_name)[1].lower()
            
            if safe_name == "all.am":
                return
                
            if safe_name == "google-services.json":
                inject_firebase_config(content, values_dir)
                return

            if safe_name == "cood.txt":
                perms = extract_permissions_from_cood(content, db_rules)
                with translation_lock:
                    shared_state["permissions_xml"] = perms
                return

            if ext == '.azim':
                lexer = Lexer(content, db_rules)
                parser = Parser(lexer.tokenize())
                ast = parser.parse()
                with translation_lock:
                    shared_state["ast_forest"].append(ast)
                processed_content = content 
            else:
                processed_content = trie.replace(content) if ext not in ['.xml', '.js', '.html', '.css', '.json'] else content
            
            processed_content = apply_source_masking(processed_content, ext)
            file_hash = hashlib.sha256(processed_content.encode('utf-8')).hexdigest()
            
            with translation_lock:
                core_hashes[safe_name] = file_hash
            
            if ext == '.bn':
                if 'manifest' in safe_name.lower() or 'ম্যানিফেস্ট' in safe_name:
                    with translation_lock:
                        shared_state["manifest_content"] = processed_content
                else:
                    clean_name = safe_name.replace('.bn', '.xml').replace('ডিজাইন', 'activity_main')
                    with open(os.path.join(layout_dir, clean_name), "w", encoding="utf-8") as f:
                        f.write(processed_content)
            elif ext == '.ajim':
                clean_name = safe_name.replace('.ajim', '.xml')
                wrapped_content = f'<?xml version="1.0" encoding="utf-8"?>\n<resources>\n{processed_content}\n</resources>'
                with open(os.path.join(values_dir, clean_name), "w", encoding="utf-8") as f:
                    f.write(wrapped_content)
            elif ext != '.azim':
                with open(os.path.join(assets_dir, safe_name), "w", encoding="utf-8") as f:
                    f.write(processed_content)

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(process_file, fname, fdata) for fname, fdata in files_data.items()]
            for future in futures:
                future.result() 

        manifest_content = shared_state["manifest_content"]
        permissions_xml = shared_state["permissions_xml"]
        ast_forest = shared_state["ast_forest"]

        if manifest_content and "android" in target_os:
            if permissions_xml:
                manifest_content = re.sub(r'(<application\b)', f'{permissions_xml}\n    \\1', manifest_content, flags=re.IGNORECASE)
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(manifest_content)

        with open(os.path.join(assets_dir, "hash_lock.json"), "w", encoding="utf-8") as f:
            json.dump(core_hashes, f, indent=4)
            
        dummy_dir = os.path.join(base_dir, "sys_dummy")
        generate_honey_pots(dummy_dir)
        
        native_env = os.environ.copy()
        out_filename = ""
        
        if "android" in target_os:
            aapt2_cmd, android_jar = get_android_tools()
            res_zip = os.path.join(base_dir, "compiled_res.zip")
            
            safe_run([aapt2_cmd, "compile", "--dir", res_dir, "-o", res_zip], env=native_env, cwd=base_dir)
            unsigned_apk = os.path.join(base_dir, "app-res.apk")
            safe_run([aapt2_cmd, "link", res_zip, "--manifest", manifest_path, "-I", android_jar, "-o", unsigned_apk], env=native_env, cwd=base_dir)
            
            dex_out = os.path.join(base_dir, "classes.dex")
            for idx, ast in enumerate(ast_forest):
                generate_smali_from_ast(ast, smali_dir, idx)
            
            safe_run(["java", "-jar", "/opt/smali.jar", "assemble", smali_dir, "-o", dex_out], env=native_env, cwd=base_dir)
                
            keystore_path = generate_unique_keystore(user_id)
            
            if build_type == ".aab":
                proto_apk = os.path.join(base_dir, "app-proto.apk")
                safe_run([aapt2_cmd, "link", "--proto-format", "-o", proto_apk, "-I", android_jar, "--manifest", manifest_path, "-R", res_zip, "--auto-add-overlay"], env=native_env, cwd=base_dir)
                
                extracted_proto = os.path.join(base_dir, "extracted_proto")
                with zipfile.ZipFile(proto_apk, 'r') as zf:
                    zf.extractall(extracted_proto)
                    
                dex_dir = os.path.join(extracted_proto, "dex")
                os.makedirs(dex_dir, exist_ok=True)
                if os.path.exists(dex_out):
                    shutil.copy(dex_out, os.path.join(dex_dir, "classes.dex"))
                    
                base_zip = os.path.join(base_dir, "base.zip")
                shutil.make_archive(base_zip.replace('.zip', ''), 'zip', extracted_proto)
                
                aab_out = os.path.join(base_dir, "app.aab")
                safe_run(["bundletool", "build-bundle", f"--modules={base_zip}", f"--output={aab_out}"], env=native_env, cwd=base_dir)
                safe_run(["jarsigner", "-keystore", keystore_path, "-storepass", "android", aab_out, "androiddebugkey"], env=native_env, cwd=base_dir)
                
                out_filename = f"app_{build_id}.aab"
                shutil.copy(aab_out, os.path.join("downloads", out_filename))
            else:
                if os.path.exists(dex_out):
                    with zipfile.ZipFile(unsigned_apk, 'a') as zf:
                        zf.write(dex_out, 'classes.dex')
                        
                aligned_apk = os.path.join(base_dir, "app-aligned.apk")
                safe_run(["zipalign", "-f", "-p", "4", unsigned_apk, aligned_apk], env=native_env, cwd=base_dir)
                
                final_apk = os.path.join("downloads", f"app_{build_id}.apk")
                safe_run(["apksigner", "sign", "--ks", keystore_path, "--ks-pass", "pass:android", "--out", final_apk, aligned_apk], env=native_env, cwd=base_dir)
                out_filename = f"app_{build_id}.apk"

        elif "windows" in target_os or "ios" in target_os or "mac" in target_os:
            llvm_ir_file = os.path.join(base_dir, "module.ll")
            
            module, builder = init_llvm_environment()
            
            for ast in ast_forest:
                inject_ast_to_llvm(ast, builder, module)
                
            ir_code = finalize_llvm_module(module, builder)
                
            with open(llvm_ir_file, "w") as f:
                f.write(ir_code)
                
            obj_file = os.path.join(base_dir, "module.o")
            safe_run(["llc", "-filetype=obj", llvm_ir_file, "-o", obj_file], env=native_env, cwd=base_dir)
            
            if "windows" in target_os:
                exe_out = os.path.join("downloads", f"app_{build_id}.exe")
                safe_run(["clang", obj_file, "-o", exe_out], env=native_env, cwd=base_dir)
                out_filename = f"app_{build_id}.exe"

            elif "ios" in target_os or "mac" in target_os:
                payload_dir = os.path.join(base_dir, "Payload")
                app_bundle_dir = os.path.join(payload_dir, "App.app")
                os.makedirs(app_bundle_dir, exist_ok=True)
                
                bin_out = os.path.join(app_bundle_dir, "App")
                ios_sdk = get_ios_sdk()
                if ios_sdk:
                    safe_run(["clang", obj_file, "-o", bin_out, "-arch", "arm64", "-isysroot", ios_sdk], env=native_env, cwd=base_dir)
                else:
                    safe_run(["clang", obj_file, "-o", bin_out, "-arch", "arm64"], env=native_env, cwd=base_dir)
                
                os.chmod(bin_out, os.stat(bin_out).st_mode | stat.S_IEXEC)
                
                try:
                    safe_run(["rcodesign", "sign", app_bundle_dir], env=native_env, cwd=base_dir)
                except:
                    pass 
                
                ipa_out = os.path.join("downloads", f"app_{build_id}.ipa")
                shutil.make_archive(ipa_out.replace('.ipa', ''), 'zip', base_dir, "Payload")
                
                if os.path.exists(ipa_out.replace('.ipa', '.zip')):
                    os.rename(ipa_out.replace('.ipa', '.zip'), ipa_out)
                    
                out_filename = f"app_{build_id}.ipa"
            
        else:
            raise Exception(f"Fatal Error: Unsupported OS target specified in all.am: {target_os}")

    except Exception as e:
        trc = traceback.format_exc()
        clean_trc = sanitize_traceback(trc, base_dir)
        raise Exception(f"Compiler Error:\n{clean_trc}")

    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
        
    return out_filename