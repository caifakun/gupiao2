import { createApp } from "vue";
import { ElAlert, ElButton, ElCheckbox, ElConfigProvider, ElDialog, ElForm, ElFormItem, ElInput, ElOption, ElSelect, ElTable, ElTableColumn, ElTag } from "element-plus";
import "element-plus/dist/index.css";
import "element-plus/theme-chalk/dark/css-vars.css";
import "./styles/workspace.css";
import "./styles/theme.css";
import App from "./App.vue";

const app = createApp(App);
for (const component of [ElAlert, ElButton, ElCheckbox, ElConfigProvider, ElDialog, ElForm, ElFormItem, ElInput, ElOption, ElSelect, ElTable, ElTableColumn, ElTag]) app.use(component);
app.mount("#app");
