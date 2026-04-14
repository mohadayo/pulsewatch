import { app } from "./app";

const PORT = parseInt(process.env.GATEWAY_PORT || "3000", 10);

app.listen(PORT, "0.0.0.0", () => {
  console.log(
    `${new Date().toISOString()} [INFO] gateway: Starting Gateway Service on port ${PORT}`
  );
});
