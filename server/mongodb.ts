import dns from "dns";
import dotenv from "dotenv";
import mongoose from "mongoose";

dotenv.config();

const MONGO_URI = process.env.MONGODB_URI|| "mongodb://localhost:27017/resume-builder";
let isConnected = false;

function configureAtlasDns() {
  if (!MONGO_URI.startsWith("mongodb+srv://")) {
    return;
  }

  const configuredServers = (process.env.MONGODB_DNS_SERVERS || "1.1.1.1,8.8.8.8")
    .split(",")
    .map((server) => server.trim())
    .filter(Boolean);

  try {
    dns.setServers(configuredServers);
    console.log("Configured DNS servers for MongoDB SRV lookup:", configuredServers.join(", "));
  } catch (error) {
    console.warn("Unable to override DNS servers for MongoDB SRV lookup.", error);
  }
}

export async function connectDB() {
  if (isConnected) {
    return;
  }

  try {
    console.log("Connecting to MongoDB Atlas...");
    configureAtlasDns();
    const db = await mongoose.connect(MONGO_URI, {
      bufferCommands: false,
    });
    isConnected = db.connection.readyState === 1;
    console.log("MongoDB Atlas connected successfully.");
  } catch (error) {
    console.error("MongoDB Connection Error:", error);
    throw error;
  }
}

// User schema storing Clerk credentials, profile info, and resume settings
const userSchema = new mongoose.Schema({
  email: { type: String, required: true, unique: true },
  clerkId: { type: String, sparse: true, unique: true },
  googleId: { type: String, sparse: true },
  name: { type: String },
  picture: { type: String },
  resumeData: { type: Object, default: null },
  settings: { type: Object, default: null },
  sessionToken: { type: String, sparse: true },
  createdAt: { type: Date, default: Date.now },
  updatedAt: { type: Date, default: Date.now },
});

// Avoid any type strictness compiler warnings with Mongoose Models in tsx server
export const User = (mongoose.models.User || mongoose.model("User", userSchema)) as any;
