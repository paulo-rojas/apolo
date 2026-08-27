use std::collections::HashSet;

pub struct PermissionSet {
    allowed: HashSet<String>,
}

impl PermissionSet {
    pub fn new(capabilities: &[String]) -> Self {
        Self {
            allowed: capabilities.iter().cloned().collect(),
        }
    }

    pub fn allows(&self, capability: &str) -> bool {
        self.allowed.contains(capability)
    }
}
