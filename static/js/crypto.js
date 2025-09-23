// rsa_crypto.js

// --- Utility Functions ---
function arrayBufferToBase64(buffer) {
  return btoa(String.fromCharCode(...new Uint8Array(buffer)));
}

function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

// --- IndexedDB Helpers ---
function getKeyDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("RSAKeyDB", 1);

    request.onupgradeneeded = function (event) {
      const db = event.target.result;
      if (!db.objectStoreNames.contains("keys")) {
        db.createObjectStore("keys");
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

// --- RSA Key Generation ---
async function generateRSAKeyPair() {
  return crypto.subtle.generateKey(
    {
      name: "RSA-OAEP",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["encrypt", "decrypt"]
  );
}

async function deletePrivateKey() {
  const db = await getKeyDB();
  const tx = db.transaction("keys", "readwrite");
  const store = tx.objectStore("keys");
  return new Promise((resolve, reject) => {
    const request = store.delete("privateKey");
    request.onsuccess = () => resolve(true);
    request.onerror   = () => reject(request.error);
  });
}

// --- Export / Import Keys ---
async function exportPublicKeyToBase64(publicKey) {
  const spki = await crypto.subtle.exportKey("spki", publicKey);
  return arrayBufferToBase64(spki);
}

async function importPublicKeyFromBase64(base64) {
  const spki = base64ToArrayBuffer(base64);
  return crypto.subtle.importKey(
    "spki",
    spki,
    { name: "RSA-OAEP", hash: "SHA-256" },
    true,
    ["encrypt"]
  );
}

// --- Encrypt / Decrypt ---
async function encryptWithPublicKey(publicKey, text) {
  const encoded = new TextEncoder().encode(text);
  return crypto.subtle.encrypt({ name: "RSA-OAEP" }, publicKey, encoded);
}

async function decryptWithPrivateKey(privateKey, ciphertext) {
  const decrypted = await crypto.subtle.decrypt({ name: "RSA-OAEP" }, privateKey, ciphertext);
  return new TextDecoder().decode(decrypted);
}

async function exportPrivateKey(privateKey) {
  return crypto.subtle.exportKey("pkcs8", privateKey);
}

// --- Store / Retrieve Private Key from IndexedDB ---
async function storePrivateKey(privateKey) {
  const keyData = await exportPrivateKey(privateKey);

  const db = await getKeyDB();
  const tx = db.transaction("keys", "readwrite");
  const store = tx.objectStore("keys");

  return new Promise((resolve, reject) => {
    const request = store.put(keyData, "privateKey");
    request.onsuccess = () => resolve(true);
    request.onerror = () => reject(request.error);
  });
}

async function retrievePrivateKey() {
  const db = await getKeyDB();
  const tx = db.transaction("keys", "readonly");
  const store = tx.objectStore("keys");

  return new Promise((resolve, reject) => {
    const request = store.get("privateKey");
    request.onsuccess = async () => {
      const keyData = request.result;
      if (!keyData) return resolve(null);
      try {
        const key = await crypto.subtle.importKey(
          "pkcs8",
          keyData,
          { name: "RSA-OAEP", hash: "SHA-256" },
          true,
          ["decrypt"]
        );
        resolve(key);
      } catch (e) {
        reject(e);
      }
    };
    request.onerror = () => reject(request.error);
  });
}

// Example usage
//const { publicKey, privateKey } = await generateRSAKeyPair();
//await storePrivateKey(privateKey);
//const publicKeyBase64 = await exportPublicKeyToBase64(publicKey);
//const message = "Hello world!";
//const encrypted = await encryptWithPublicKey(publicKey, message);
//const retrievedPrivateKey = await retrievePrivateKey();
//const decrypted = await decryptWithPrivateKey(retrievedPrivateKey, encrypted);

